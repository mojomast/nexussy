from __future__ import annotations
import asyncio, json, logging, os, re, pathlib, shutil, hashlib
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from nexussy.api.schemas import (
    ArtifactRef, ArtifactUpdatedPayload, ChangedFilesManifest, ComplexityLevel,
    ComplexityProfile, DevelopReport, DonePayload, ErrorCode, ErrorResponse,
    EventEnvelope, GitEventAction, GitEventPayload, InterviewArtifact,
    InterviewQuestionAnswer, JsonValue, MergeReport, PausePayload,
    PipelineStartRequest, ReviewReport, RunStartResponse, RunStatus,
    RunSummary, SSEEventType, SessionCreateRequest, SessionDetail,
    SessionSummary, StageName, StageRunStatus, StageStatusSchema,
    StageTransitionPayload, TokenUsage, ToolName, ValidationIssue,
    ValidationReport, Worker, WorkerRole, WorkerStatus, WorkerTaskPayload,
    WorkerTaskStatus,
)
from nexussy.artifacts.store import safe_write, artifact_path, sha256_text
from nexussy.checkpoint import STAGE_ORDER, latest_checkpoint, resume_from_checkpoint, save_checkpoint
from nexussy.providers import active_rate_limit, complete, effective_secret_env, mock_requested, model_available, provider_error_for_model, provider_for_model, select_stage_model
from nexussy.session import now_utc
from nexussy.swarm.gitops import init_repo, create_worktree, commit_worker, merge_no_ff, extract_changed_files, prune_worktrees, remove_worktree
from nexussy.swarm.locks import write_requires_lock
from nexussy.swarm.pi_rpc import spawn_pi_worker
from nexussy.swarm.roles import enforce_tool

logger = logging.getLogger(__name__)
STAGES=[StageName.interview,StageName.design,StageName.validate,StageName.plan,StageName.review,StageName.develop]

@dataclass
class WorkerMergeResult:
    worker: Worker
    worker_id: str

def slugify(name: str) -> str:
    s=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:63]
    return s or "project"

def complexity(desc: str, existing: bool=False) -> ComplexityProfile:
    d=desc.lower(); signals={}; score=0
    def has(pattern: str) -> bool:
        return re.search(pattern, d) is not None
    checks=[("multiple_languages",10, has(r"\bfrontend\b\s+and\s+\bbackend\b|\btypescript\b|\bpython\b|\bjava\b|\bgo\b|\bgolang\b")),("persistence",10, has(r"\bdatabase\b|\bsqlite\b|\bpostgres\b|\bpersist\b")),("auth",15, has(r"\bauth(entication|orization)?\b|\bsecurity\b|\bpassword\b")),("external_api",10,has(r"\bapi\b")),("ui_backend",15, has(r"\bui\b|\bdashboard\b|\bweb\b|\btui\b")),("deployment",10, has(r"\bdeploy\b|\bdocker\b|\binfra\b")),("existing_repo",10, existing),("qa",10, has(r"\btest\b|\bqa\b")),("ambiguous",15, len(desc.split())<8)]
    if not any(c[2] for c in checks): signals["simple"]=5; score+=5
    for k,pts,on in checks:
        if on: signals[k]=pts; score+=pts
    score=min(score,100)
    if score<=25: lvl=ComplexityLevel.minimal; pc=2; gs=3
    elif score<=60: lvl=ComplexityLevel.standard; pc=4; gs=4
    else: lvl=ComplexityLevel.detailed; pc=6; gs=5
    return ComplexityProfile(level=lvl,score=score,phase_count=pc,task_group_size=gs,template_depth=lvl,signals=signals,rationale="Deterministic rubric from SPEC section 11.3")

class Engine:
    def __init__(self, db, config):
        self.db=db; self.config=config; self.queues:dict[str,set[asyncio.Queue]]={}; self.tasks={}; self.paused={}; self.interview_waiters:dict[str,asyncio.Future]={}; self.interview_questions:dict[str,list[InterviewQuestionAnswer]]={}; self.session_runs:dict[str,str]={}; self.active_worker_rpcs:dict[str,list]={}; self.blocked_previous_status:dict[str,str]={}; self.git_lock=asyncio.Lock(); self.provider_env_cache:dict|None=None

    def invalidate_provider_cache(self):
        self.provider_env_cache=None

    async def _persist_event(self, env: EventEnvelope):
        typ = env.type.value if hasattr(env.type, "value") else env.type
        def tx(con):
            con.execute(
                "INSERT INTO events(event_id, run_id, sequence, type, payload_json, created_at) "
                "VALUES(?, ?, (SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?), ?, ?, ?)",
                (env.event_id, env.run_id, env.run_id, typ, json.dumps(env.model_dump(mode="json")), env.ts.isoformat())
            )
            row=con.execute("SELECT sequence FROM events WHERE event_id=?",(env.event_id,)).fetchone()
            if row:
                env.sequence=row["sequence"]
                con.execute("UPDATE events SET payload_json=? WHERE event_id=?",(json.dumps(env.model_dump(mode="json")),env.event_id))
        await self.db.write(tx)

    async def emit(self, typ:SSEEventType, session_id:str, run_id:str, payload):
        env=EventEnvelope(sequence=0,type=typ,session_id=session_id,run_id=run_id,payload=payload.model_dump(mode="json") if hasattr(payload,"model_dump") else payload)
        await self._persist_event(env)
        for q in list(self.queues.get(run_id,set())):
            try: q.put_nowait(env)
            except asyncio.QueueFull:
                self.queues.get(run_id,set()).discard(q)
                slow=EventEnvelope(sequence=0,type=SSEEventType.pipeline_error,session_id=session_id,run_id=run_id,payload=ErrorResponse(error_code=ErrorCode.sse_client_slow,message="SSE client queue exceeded",retryable=True).model_dump(mode="json"))
                await self._persist_event(slow)
                try: q.get_nowait()
                except asyncio.QueueEmpty: pass
                try: q.put_nowait(slow)
                except asyncio.QueueFull: pass
        return env
    async def replay(self, run_id, last_event_id=None, after_sequence=0, limit=10000):
        if last_event_id:
            rows=await self.db.read("SELECT sequence FROM events WHERE event_id=?",(last_event_id,)); after_sequence=rows[0]["sequence"] if rows else after_sequence
        rows=await self.db.read("SELECT payload_json FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",(run_id,after_sequence,limit))
        return [EventEnvelope.model_validate_json(r["payload_json"]) for r in rows]
    async def create_session(self, req:SessionCreateRequest|PipelineStartRequest):
        slug=req.project_slug or slugify(req.project_name)
        if await self.db.read("SELECT session_id FROM sessions WHERE project_slug=?", (slug,)):
            slug = f"{slug[:56].rstrip('-')}-{hashlib.sha1(str(uuid4()).encode()).hexdigest()[:6]}"
        sid=str(uuid4()); now=now_utc();
        root=pathlib.Path(self.config.projects_dir).expanduser()/slug; main=root/"main"; main.mkdir(parents=True,exist_ok=True)
        await self.db.init_project(str(root), self.config.database.project_relative_path)
        if req.existing_repo_path and pathlib.Path(req.existing_repo_path).exists():
            pass
        detail=SessionDetail(session=SessionSummary(session_id=sid,project_name=req.project_name,project_slug=slug,created_at=now,updated_at=now),project_root=str(root),main_worktree=str(main),artifacts=[],runs=[])
        await self.db.write(lambda con: con.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",(sid,slug,req.project_name,"created",now.isoformat(),now.isoformat(),detail.model_dump_json())))
        return detail
    async def start(self, req:PipelineStartRequest):
        allow_mock = mock_requested(req.metadata)
        selected = {st.value: select_stage_model(self.config, st.value, { (k.value if hasattr(k,'value') else k): v for k,v in req.model_overrides.items() }) for st in STAGES}
        fallbacks=[]
        for st, model in selected.items():
            provider = provider_for_model(model)
            limited = await active_rate_limit(self.db, provider, model)
            if limited:
                raise ProviderStartError(ErrorResponse(error_code=ErrorCode.rate_limited, message="provider rate limited", details={"provider":provider,"model":model,"reset_at":limited["reset_at"]}, retryable=True))
            if not model_available(model, allow_mock=allow_mock):
                if self.config.providers.allow_fallback and model_available(self.config.providers.default_model, allow_mock=allow_mock):
                    fallbacks.append({"stage":st,"requested_model":model,"fallback_model":self.config.providers.default_model})
                    selected[st] = self.config.providers.default_model
                    continue
                raise ProviderStartError(provider_error_for_model(model))
        start_stage=req.start_stage
        if req.resume_run_id and await resume_from_checkpoint(self.db, req.resume_run_id, req.start_stage):
            checkpoint=await latest_checkpoint(self.db, req.resume_run_id)
            if checkpoint:
                next_index=min(STAGE_ORDER.index(checkpoint.stage.value if hasattr(checkpoint.stage, 'value') else checkpoint.stage)+1, len(STAGES)-1)
                candidate=STAGES[next_index]
                if STAGES.index(candidate) > STAGES.index(req.start_stage): start_stage=candidate
        effective_req=req.model_copy(update={"start_stage":start_stage})
        detail=await self.create_session(effective_req); rid=effective_req.resume_run_id or str(uuid4()); now=now_utc();
        run=RunSummary(run_id=rid,session_id=detail.session.session_id,status=RunStatus.running,current_stage=effective_req.start_stage,started_at=now)
        await self.db.write(lambda con: (con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?)",(rid,detail.session.session_id,"running",effective_req.start_stage.value,now.isoformat(),None,run.usage.model_dump_json())), con.execute("UPDATE sessions SET status=?, updated_at=?, detail_json=? WHERE session_id=?",("running",now.isoformat(),detail.model_dump_json(),detail.session.session_id))))
        for st in STAGES: await self.db.write(lambda con, st=st: con.execute("INSERT OR REPLACE INTO stage_runs VALUES(?,?,?,?,?,?,?)",(rid,st.value,"pending",0,None,None,None)))
        await self.emit(SSEEventType.run_started, detail.session.session_id, rid, run)
        for fb in fallbacks:
            await self.emit(SSEEventType.pipeline_error, detail.session.session_id, rid, ErrorResponse(error_code=ErrorCode.model_unavailable,message="provider/model unavailable; using fallback model",details=fb,retryable=True))
        self.session_runs[detail.session.session_id]=rid
        self.tasks[rid]=asyncio.create_task(self._run(effective_req, detail, run, selected, allow_mock))
        return RunStartResponse(session_id=detail.session.session_id,run_id=rid,stream_url=f"/pipeline/runs/{rid}/stream",status_url=f"/pipeline/status?run_id={rid}")
    async def _run(self, req, detail, run, selected_models=None, allow_mock=False):
        start=STAGES.index(req.start_stage); stop=STAGES.index(req.stop_after_stage) if req.stop_after_stage else len(STAGES)-1
        artifacts=[]; root=detail.main_worktree; prev=None
        cp=complexity(req.description, bool(req.existing_repo_path))
        try:
            i = start
            review_iterations = 0
            validation_iterations = 0
            review_feedback_for_plan = ""
            while i <= stop:
                st = STAGES[i]
                while self.paused.get(run.run_id): await asyncio.sleep(.05)
                attempt = (validation_iterations + 1) if st == StageName.validate else ((review_iterations + 1) if st == StageName.review else 1)
                t0=now_utc(); await self._update_stage_status(run.run_id, st, "running", attempt=attempt, started_at=t0)
                await self.emit(SSEEventType.stage_transition, detail.session.session_id, run.run_id, StageTransitionPayload(from_stage=prev,to_stage=st,from_status=StageRunStatus.passed if prev else None,to_status=StageRunStatus.running,reason="stage started"))
                made=await self._artifacts_for_stage(st, req, detail, run.run_id, cp, root, selected_models or {}, allow_mock, review_feedback_for_plan)
                artifacts.extend(made)
                if st == StageName.validate:
                    validation_iterations += 1
                    fail_for = int(req.metadata.get("validate_fail_iterations", 0) or (self.config.stages.validate.max_iterations or 3 if req.metadata.get("force_validate_fail") else 0))
                    validation_passed = await self._latest_report_passed(run.run_id, "validation_report", True)
                    if validation_iterations <= fail_for or not validation_passed:
                        await self._update_stage_status(run.run_id, StageName.validate, "retrying", attempt=validation_iterations, error=ErrorResponse(error_code=ErrorCode.validation_error,message="validation issues require design correction",retryable=True))
                        if validation_iterations < (self.config.stages.validate.max_iterations or 3):
                            await self.emit(SSEEventType.stage_transition, detail.session.session_id, run.run_id, StageTransitionPayload(from_stage=StageName.validate,to_stage=StageName.design,from_status=StageRunStatus.failed,to_status=StageRunStatus.retrying,reason="validation corrections returned to design"))
                            i = STAGES.index(StageName.design); prev = StageName.validate; continue
                        raise RuntimeError("validate max iterations exceeded")
                if st == StageName.review and (req.metadata.get("force_review_fail") or not await self._latest_report_passed(run.run_id, "review_report", True)):
                    review_iterations += 1
                    review_feedback_for_plan = await self._latest_review_feedback(run.run_id)
                    await self._update_stage_status(run.run_id, StageName.review, "retrying", attempt=review_iterations, error=ErrorResponse(error_code=ErrorCode.stage_failed,message="review feedback requires plan correction",retryable=True))
                    if review_iterations < int(req.metadata.get("review_fail_iterations", self.config.stages.review.max_iterations or 2)):
                        await self.emit(SSEEventType.stage_transition, detail.session.session_id, run.run_id, StageTransitionPayload(from_stage=StageName.review,to_stage=StageName.plan,from_status=StageRunStatus.failed,to_status=StageRunStatus.retrying,reason="review feedback returned to plan"))
                        i = STAGES.index(StageName.plan); prev = StageName.review; continue
                    raise RuntimeError("review max iterations exceeded")
                fin=now_utc(); await self._update_stage_status(run.run_id, st, "passed", finished_at=fin)
                await self.emit(SSEEventType.stage_status, detail.session.session_id, run.run_id, StageStatusSchema(stage=st,status=StageRunStatus.passed,attempt=1,finished_at=fin,output_artifacts=made))
                ck=await save_checkpoint(self.db, run.run_id, st, f".nexussy/checkpoints/{st.value}.json", sha256_text(st.value))
                await self.emit(SSEEventType.checkpoint_saved, detail.session.session_id, run.run_id, ck); prev=st; i += 1
                if st == StageName.plan:
                    review_feedback_for_plan = ""
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=?, current_stage=? WHERE run_id=?",("passed",now_utc().isoformat(),prev.value if prev else None,run.run_id)))
            await self.emit(SSEEventType.done, detail.session.session_id, run.run_id, DonePayload(final_status=RunStatus.passed,summary="pipeline completed",artifacts=artifacts,usage=TokenUsage()))
        except asyncio.CancelledError:
            fut=self.interview_waiters.pop(detail.session.session_id, None)
            if fut and not fut.done():
                fut.cancel()
            self.interview_questions.pop(detail.session.session_id, None)
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?",("cancelled",now_utc().isoformat(),run.run_id)))
            raise
        except Exception as e:
            er=ErrorResponse(error_code=ErrorCode.stage_failed,message=str(e),retryable=False)
            self.paused.pop(run.run_id, None)
            logger.exception("pipeline run %s failed at stage %s: %s", run.run_id, prev, e)
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?",("failed",now_utc().isoformat(),run.run_id)))
            await self.emit(SSEEventType.pipeline_error, detail.session.session_id, run.run_id, er)
            await self.emit(SSEEventType.done, detail.session.session_id, run.run_id, DonePayload(final_status=RunStatus.failed,summary="pipeline failed",artifacts=artifacts,usage=TokenUsage(),error=er))
    async def _save_art(self, run_id, session_id, root, kind, text, phase=None):
        rel=artifact_path(kind, phase); meta=safe_write(root, rel, text); ref=ArtifactRef(kind=kind,path=rel,sha256=meta["sha256"],bytes=meta["bytes"],phase_number=phase)
        await self.emit(SSEEventType.artifact_updated, session_id, run_id, ArtifactUpdatedPayload(artifact=ref,action="created"))
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?,?,?,?)",(run_id,kind,rel,ref.sha256,ref.bytes,ref.updated_at.isoformat(),text,phase)))
        return ref

    async def execute_worker_tool(self, run_id: str, worker_id: str, tool: ToolName, arguments: dict[str, JsonValue] | None = None):
        arguments=arguments or {}
        rows=await self.db.read("SELECT worker_json FROM workers WHERE run_id=? AND worker_id=?",(run_id,worker_id))
        if not rows: raise KeyError("worker")
        worker=Worker.model_validate_json(rows[0]["worker_json"])
        session_rows=await self.db.read("SELECT session_id FROM runs WHERE run_id=?",(run_id,))
        sid=session_rows[0]["session_id"] if session_rows else "unknown"
        tool_value=tool.value if hasattr(tool,"value") else tool
        await self.emit(SSEEventType.tool_call,sid,run_id,{"worker_id":worker_id,"tool":tool_value,"arguments":arguments})
        try:
            path=arguments.get("path") if isinstance(arguments, dict) else None
            enforce_tool(worker.role, tool, path)
            if tool in {ToolName.write_file, ToolName.edit_file} and path:
                await write_requires_lock(self.db, run_id, str(path), worker_id)
            payload={"worker_id":worker_id,"tool":tool_value,"success":True,"result":{}}
        except PermissionError as e:
            payload={"worker_id":worker_id,"tool":tool_value,"success":False,"error_code":str(e) or "forbidden"}
        await self.emit(SSEEventType.tool_output,sid,run_id,payload)
        return payload
    async def _provider_text(self, st: StageName, sid: str, rid: str, prompt: str, selected_models, allow_mock: bool) -> str:
        model = (selected_models or {}).get(st.value) or self.config.providers.default_model
        stage_cfg = getattr(self.config.stages, st.value, None)
        max_retries = max(1, int(getattr(stage_cfg, "max_retries", self.config.providers.max_retries) or self.config.providers.max_retries or 1))
        last_error = None
        for attempt in range(max_retries):
            try:
                if self.provider_env_cache is None:
                    self.provider_env_cache = effective_secret_env()
                result = await complete(st.value, prompt, model, allow_mock=allow_mock, timeout_s=self.config.providers.request_timeout_s, _env=self.provider_env_cache)
                break
            except Exception as e:
                last_error = e
                if attempt + 1 >= max_retries:
                    raise
                await asyncio.sleep((self.config.providers.retry_base_ms / 1000) * (2 ** attempt))
        else:
            raise last_error or RuntimeError("provider failed")
        usage = TokenUsage(**result.usage)
        await self.emit(SSEEventType.cost_update, sid, rid, usage)
        return result.text

    async def _update_stage_status(self, run_id: str, stage: StageName, status: str|StageRunStatus, *, attempt: int|None=None, started_at: datetime|None=None, finished_at: datetime|None=None, error: ErrorResponse|None=None):
        status_value=status.value if hasattr(status,"value") else status
        await self.db.write(lambda con: con.execute(
            "UPDATE stage_runs SET status=?,attempt=COALESCE(?,attempt),started_at=COALESCE(?,started_at),finished_at=COALESCE(?,finished_at),error_json=? WHERE run_id=? AND stage=?",
            (status_value,attempt,started_at.isoformat() if started_at else None,finished_at.isoformat() if finished_at else None,error.model_dump_json() if error else None,run_id,stage.value)))

    async def _latest_artifact_text(self, run_id: str, kind: str) -> str:
        rows=await self.db.read("SELECT content_text FROM artifacts WHERE run_id=? AND kind=? ORDER BY updated_at DESC LIMIT 1",(run_id,kind))
        return rows[0]["content_text"] if rows else ""

    async def _latest_report_passed(self, run_id: str, kind: str, default: bool) -> bool:
        text=await self._latest_artifact_text(run_id, kind)
        if not text: return default
        try:
            data=json.loads(text)
            return bool(data.get("passed", default)) if isinstance(data, dict) else default
        except Exception:
            return default

    async def _latest_review_feedback(self, run_id: str) -> str:
        text=await self._latest_artifact_text(run_id, "review_report")
        if not text: return ""
        try:
            data=json.loads(text)
            return str(data.get("feedback_for_plan_stage") or "") if isinstance(data, dict) else ""
        except Exception:
            return ""

    def _provider_declared_passed(self, text: str, default: bool) -> bool:
        try:
            data=json.loads((text or "").strip())
            if isinstance(data, dict) and isinstance(data.get("passed"), bool):
                return data["passed"]
        except Exception:
            pass
        return default

    def _strip_markdown_fences(self, text: str) -> str:
        stripped=(text or "").strip()
        m=re.fullmatch(r"```(?:[a-zA-Z0-9_-]+)?\s*\n([\s\S]*?)\n```", stripped)
        return (m.group(1) if m else stripped).strip() + "\n"

    def _issues_from_provider_text(self, text: str) -> list[ValidationIssue]:
        raw=(text or "").strip()
        data=None
        try: data=json.loads(raw)
        except Exception: data=None
        source=[]
        if isinstance(data, dict): source=data.get("issues") or []
        elif isinstance(data, list): source=data
        issues=[]
        for idx,item in enumerate(source, start=1):
            if isinstance(item, dict):
                msg=str(item.get("message") or item.get("issue") or item.get("text") or "").strip()
                if not msg: continue
                sev=str(item.get("severity") or "error").lower()
                if sev not in {"info","warning","error","blocker"}: sev="error"
                issues.append(ValidationIssue(severity=sev,category=str(item.get("category") or "provider"),message=msg,artifact_path=item.get("artifact_path"),anchor=item.get("anchor"),fix_required=bool(item.get("fix_required", sev in {"error","blocker"}))))
            elif isinstance(item, str) and item.strip():
                issues.append(ValidationIssue(severity="error",category="provider",message=item.strip(),fix_required=True))
        if issues: return issues
        for line in raw.splitlines():
            lower=line.lower().strip(" -*)\t")
            if lower.startswith(("issue:","error:","blocker:","fix:")):
                sev="blocker" if lower.startswith("blocker:") else "error"
                issues.append(ValidationIssue(severity=sev,category="provider",message=line.split(":",1)[-1].strip() or line.strip(),fix_required=True))
        return issues

    def _corrected_design_from_validation(self, provider_text: str, original_design: str) -> str:
        try: data=json.loads((provider_text or "").strip())
        except Exception: data=None
        if isinstance(data, dict):
            for key in ("corrected_design","validated_design","design"):
                val=data.get(key)
                if isinstance(val,str) and val.strip(): return val.strip()+"\n"
        return original_design or provider_text

    def _review_feedback(self, provider_text: str, issues: list[ValidationIssue]) -> str:
        if issues: return "\n".join(i.message for i in issues)
        try:
            data=json.loads((provider_text or "").strip())
            if isinstance(data, dict) and isinstance(data.get("feedback_for_plan_stage"), str): return data["feedback_for_plan_stage"]
        except Exception: pass
        return ""

    def _devplan_with_required_anchors(self, provider_text: str) -> tuple[str,bool]:
        body=self._strip_markdown_fences(provider_text)
        start="<!-- NEXT_TASK_GROUP_START -->"; end="<!-- NEXT_TASK_GROUP_END -->"
        if body.count(start)==1 and body.count(end)==1 and body.index(start) < body.index(end): return body, False
        task_re=re.compile(r"(?m)(^\s*- \[ \][\s\S]*?)(?=\n\s*\n|\Z)")
        m=task_re.search(body)
        if m:
            tasks=m.group(1).rstrip()
            wrapped=f"{start}\n{tasks}\n{end}"
            body=body[:m.start()] + wrapped + body[m.end():]
            if "<!-- PROGRESS_LOG_START -->" not in body:
                body="# DevPlan\n\n<!-- PROGRESS_LOG_START -->\n- Created by nexussy.\n<!-- PROGRESS_LOG_END -->\n\n" + body.lstrip()
            return body.rstrip()+"\n", True
        fallback="# DevPlan\n<!-- PROGRESS_LOG_START -->\n- Created by nexussy.\n- Warning: provider plan output lacked a task list with NEXT_TASK_GROUP anchors.\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: implement requested work. Acceptance: tests pass.\n<!-- NEXT_TASK_GROUP_END -->\n"
        return fallback, True

    def _parse_interview_questions(self, text: str) -> list[InterviewQuestionAnswer]:
        try: raw=json.loads(text)
        except Exception: raw=[]
        if not isinstance(raw, list): raw=[]
        questions=[]; seen=set()
        for idx, item in enumerate(raw[:8], start=1):
            if not isinstance(item, dict): continue
            qid=str(item.get("id") or item.get("question_id") or f"q{idx}").strip() or f"q{idx}"
            question=str(item.get("question") or "").strip()
            if not question or qid in seen: continue
            seen.add(qid); questions.append(InterviewQuestionAnswer(question_id=qid,question=question,answer="pending",source="user"))
        if len(questions) < 4:
            questions=[InterviewQuestionAnswer(question_id="q_name",question="What is the name of your project?",answer="pending",source="user"),InterviewQuestionAnswer(question_id="q_lang",question="What programming language(s) will you use?",answer="pending",source="user"),InterviewQuestionAnswer(question_id="q_desc",question="Describe what your project does in 1-2 sentences.",answer="pending",source="user"),InterviewQuestionAnswer(question_id="q_type",question="What type of project is this? (API, Web App, CLI, Game, etc.)",answer="pending",source="user")]
        return questions[:8]

    def _parse_auto_answers(self, text: str, questions: list[InterviewQuestionAnswer], req: PipelineStartRequest) -> dict[str,str]:
        try: raw=json.loads(text)
        except Exception: raw={}
        answers = raw.get("answers", raw) if isinstance(raw, dict) else {}
        out={}
        for q in questions:
            answer = answers.get(q.question_id) if isinstance(answers, dict) else None
            if not isinstance(answer, str) or not answer.strip():
                lower=q.question.lower()
                if "name" in lower: answer=req.project_name
                else: answer=req.description
            out[q.question_id]=answer.strip()
        return out

    def _interview_summary(self, artifact: InterviewArtifact|None) -> str:
        if not artifact: return ""
        lines=["Project Requirements (from Interview)"]
        for qa in artifact.questions:
            lines.append(f"{qa.question.replace('?', '').strip()}: {qa.answer}")
        if artifact.requirements: lines.append("Requirements: " + "; ".join(artifact.requirements))
        return "\n".join(lines)

    async def _latest_interview_artifact(self, run_id: str) -> InterviewArtifact|None:
        rows=await self.db.read("SELECT content_text FROM artifacts WHERE run_id=? AND kind='interview' ORDER BY updated_at DESC LIMIT 1",(run_id,))
        return InterviewArtifact.model_validate_json(rows[0]["content_text"]) if rows else None

    async def submit_interview_answers(self, session_id: str, answers: dict[str,str]) -> InterviewArtifact:
        rid=self.session_runs.get(session_id)
        if not rid:
            rows=await self.db.read("SELECT run_id FROM runs WHERE session_id=? ORDER BY started_at DESC LIMIT 1",(session_id,)); rid=rows[0]["run_id"] if rows else None
        if not rid: raise KeyError("run")
        current=None; questions=self.interview_questions.get(session_id)
        if not questions:
            current=await self._latest_interview_artifact(rid); questions=current.questions if current else []
        missing=[q.question_id for q in questions if not answers.get(q.question_id, "").strip()]
        if missing: raise ValueError([{"loc":["body","answers"],"msg":"missing interview answers","type":"value_error","ctx":{"missing":missing}}])
        answered=[InterviewQuestionAnswer(question_id=q.question_id,question=q.question,answer=answers[q.question_id].strip(),source="user") for q in questions]
        fut=self.interview_waiters.get(session_id)
        if fut and not fut.done(): fut.set_result(answered)
        self.paused.pop(rid,None)
        await self.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("running",rid)))
        await self.emit(SSEEventType.pause_state_changed,session_id,rid,PausePayload(paused=False,reason="interview answered"))
        current=current or await self._latest_interview_artifact(rid)
        return InterviewArtifact(project_name=current.project_name if current else "pending",project_slug=current.project_slug if current else "pending",description=current.description if current else "pending",questions=answered,requirements=[a.answer for a in answered])

    async def _artifacts_for_stage(self, st, req, detail, rid, cp, root, selected_models=None, allow_mock=False, review_feedback_for_plan: str=""):
        sid=detail.session.session_id
        if st==StageName.interview:
            question_prompt=("Generate a JSON array of 4-8 plain-language interview questions for a non-technical project owner. "
                             "Cover project name, primary languages, short description/requirements, project type, and optional frameworks, database, auth, deployment, and testing preferences. "
                             "Return only JSON objects with id and question fields.\n\n"
                             f"Project description: {req.description}")
            questions=self._parse_interview_questions(await self._provider_text(st, sid, rid, question_prompt, selected_models, allow_mock))
            self.interview_questions[sid]=questions
            ck=await save_checkpoint(self.db, rid, StageName.interview, ".nexussy/checkpoints/interview-questions.json", sha256_text(json.dumps([q.model_dump(mode="json") for q in questions], sort_keys=True)))
            await self.emit(SSEEventType.checkpoint_saved,sid,rid,ck)
            if req.auto_approve_interview:
                answer_prompt=("Answer these interview questions as JSON using only the project description. "
                               "Return a JSON object mapping each question id to a concise answer.\n\n"
                               f"Project name: {req.project_name}\nProject description: {req.description}\nQuestions: {json.dumps([{'id': q.question_id, 'question': q.question} for q in questions])}")
                answers=self._parse_auto_answers(await self._provider_text(st, sid, rid, answer_prompt, selected_models, allow_mock), questions, req)
                answered=[InterviewQuestionAnswer(question_id=q.question_id,question=q.question,answer=answers[q.question_id],source="auto") for q in questions]
            else:
                pending=InterviewArtifact(project_name=req.project_name,project_slug=detail.session.project_slug,description=req.description,questions=questions,requirements=[req.description])
                await self._save_art(rid,sid,root,"interview",pending.model_dump_json(indent=2))
                fut=asyncio.get_running_loop().create_future(); self.interview_waiters[sid]=fut; self.paused[rid]=True
                await self.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("paused",rid)))
                await self.emit(SSEEventType.pause_state_changed,sid,rid,PausePayload(paused=True,reason="waiting for interview answers"))
                interview_cfg=getattr(self.config.stages, "interview", None)
                timeout_s=getattr(interview_cfg, "answer_timeout_s", 3600) if interview_cfg else 3600
                try:
                    answered=await asyncio.wait_for(fut, timeout=timeout_s)
                except asyncio.TimeoutError:
                    self.interview_waiters.pop(sid,None); self.interview_questions.pop(sid,None)
                    self.paused.pop(rid,None)
                    raise RuntimeError("interview answer timeout - user did not respond in time")
                self.interview_waiters.pop(sid,None); self.interview_questions.pop(sid,None)
            ia=InterviewArtifact(project_name=req.project_name,project_slug=detail.session.project_slug,description=req.description,questions=answered,requirements=[qa.answer for qa in answered])
            return [await self._save_art(rid,sid,root,"interview",ia.model_dump_json(indent=2)), await self._save_art(rid,sid,root,"complexity_profile",cp.model_dump_json(indent=2))]
        if st==StageName.design:
            interview=self._interview_summary(await self._latest_interview_artifact(rid))
            txt=await self._provider_text(st, sid, rid, f"Create design with Goals, Architecture, Dependencies, Risks, Test Strategy for: {req.description}\n\n{interview}", selected_models, allow_mock)
            return [await self._save_art(rid,sid,root,"design_draft",txt if all(h in txt for h in ["Goals","Architecture","Dependencies","Risks","Test Strategy"]) else "# Goals\nDeliver requested project.\n# Architecture\nProvider-guided design.\n# Dependencies\nPython.\n# Risks\nUnknowns.\n# Test Strategy\nAutomated tests.\n")]
        if st==StageName.validate:
            design=await self._latest_artifact_text(rid,"design_draft")
            prompt=("Validate this design draft for completeness, internal consistency, missing dependencies, risks, and testability. "
                    "Return JSON with optional issues[] and optional corrected_design. If clean, return passed true and no issues.\n\n" + design)
            response=await self._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
            issues=self._issues_from_provider_text(response)
            corrected=self._corrected_design_from_validation(response, design)
            issue_passed=not any(i.fix_required or i.severity in {"error","blocker"} for i in issues)
            report=ValidationReport(passed=self._provider_declared_passed(response, issue_passed) and issue_passed,max_iterations=self.config.stages.validate.max_iterations or 3,issues=issues,corrected=corrected.strip()!=design.strip())
            return [await self._save_art(rid,sid,root,"validated_design",corrected), await self._save_art(rid,sid,root,"validation_report",report.model_dump_json(indent=2))]
        if st==StageName.plan:
            interview=self._interview_summary(await self._latest_interview_artifact(rid))
            feedback = f"\n\nReview feedback to address in this plan retry:\n{review_feedback_for_plan}" if review_feedback_for_plan else ""
            plan_text=await self._provider_text(st, sid, rid, f"Create a devplan.md body with PROGRESS_LOG and NEXT_TASK_GROUP anchors from interview requirements.\n\n{interview}\n\nOriginal description: {req.description}{feedback}", selected_models, allow_mock)
            dev, warned=self._devplan_with_required_anchors(plan_text)
            if warned:
                await self.emit(SSEEventType.pipeline_error,sid,rid,ErrorResponse(error_code=ErrorCode.validation_error,message="plan output required anchor repair",details={"stage":"plan"},retryable=True))
            hand="""# Handoff\n<!-- QUICK_STATUS_START -->\nPipeline plan generated.\n<!-- QUICK_STATUS_END -->\n<!-- HANDOFF_NOTES_START -->\nContinue from devplan.\n<!-- HANDOFF_NOTES_END -->\n<!-- SUBAGENT_A_ASSIGNMENT_START -->\nOwn core.\n<!-- SUBAGENT_A_ASSIGNMENT_END -->\n<!-- SUBAGENT_B_ASSIGNMENT_START -->\nOwn tui.\n<!-- SUBAGENT_B_ASSIGNMENT_END -->\n<!-- SUBAGENT_C_ASSIGNMENT_START -->\nOwn web.\n<!-- SUBAGENT_C_ASSIGNMENT_END -->\n<!-- SUBAGENT_D_ASSIGNMENT_START -->\nOwn ops.\n<!-- SUBAGENT_D_ASSIGNMENT_END -->\n"""
            refs=[await self._save_art(rid,sid,root,"devplan",dev), await self._save_art(rid,sid,root,"handoff",hand)]
            for i in range(1,cp.phase_count+1): refs.append(await self._save_art(rid,sid,root,"phase",f"# Phase {i:03d}\n<!-- PHASE_TASKS_START -->\n- [ ] Task {i}\n<!-- PHASE_TASKS_END -->\n<!-- PHASE_PROGRESS_START -->\n- pending\n<!-- PHASE_PROGRESS_END -->\n",i))
            return refs
        if st==StageName.review:
            if req.metadata.get("force_review_fail"):
                return [await self._save_art(rid,sid,root,"review_report",ReviewReport(passed=False,max_iterations=self.config.stages.review.max_iterations or 2,feedback_for_plan_stage="Fix plan issues").model_dump_json(indent=2))]
            devplan=await self._latest_artifact_text(rid,"devplan"); handoff=await self._latest_artifact_text(rid,"handoff")
            prompt=("Review this devplan and handoff for missing anchors, unclear next tasks, cross-boundary risks, and readiness for development. "
                    "Return JSON with optional issues[] and feedback_for_plan_stage. If clean, return passed true and no issues.\n\n"
                    f"DEVPLAN:\n{devplan}\n\nHANDOFF:\n{handoff}")
            response=await self._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
            issues=self._issues_from_provider_text(response)
            issue_passed=not any(i.fix_required or i.severity in {"error","blocker"} for i in issues)
            passed=self._provider_declared_passed(response, issue_passed) and issue_passed
            return [await self._save_art(rid,sid,root,"review_report",ReviewReport(passed=passed,max_iterations=self.config.stages.review.max_iterations or 2,issues=issues,feedback_for_plan_stage=self._review_feedback(response,issues)).model_dump_json(indent=2))]
        if st==StageName.develop:
            return await self._develop_stage(req, detail, rid, root, selected_models or {}, allow_mock)
        return []

    async def _develop_stage(self, req, detail, rid, root, selected_models, allow_mock):
        sid=detail.session.session_id; main=pathlib.Path(root); workers_root=main.parent/"workers"; artifacts_dir=main/".nexussy"/"artifacts"
        if allow_mock and not req.metadata.get("fake_pi_command"):
            orch_model=self.config.stages.develop.orchestrator_model or selected_models.get("develop") or self.config.providers.default_model
            orch=Worker(worker_id="orchestrator-abcdef",run_id=rid,role=WorkerRole.orchestrator,status=WorkerStatus.finished,worktree_path=str(workers_root/"orchestrator-abcdef"),branch_name="worker/orchestrator-abcdef",model=orch_model)
            await self._persist_worker(orch); await self.emit(SSEEventType.worker_spawned,sid,rid,orch)
            return [await self._save_art(rid,sid,root,"develop_report",DevelopReport(run_id=rid,passed=True,workers=[orch],tasks_total=1,tasks_passed=1).model_dump_json(indent=2)), await self._save_art(rid,sid,root,"merge_report",MergeReport(run_id=rid,base_commit="mock",merge_commit="mock",merged_workers=[orch.worker_id],passed=True).model_dump_json(indent=2)), await self._save_art(rid,sid,root,"changed_files",ChangedFilesManifest(run_id=rid,base_commit="mock",merge_commit="mock").model_dump_json(indent=2))]
        context=await self._spawn_workers(req, detail, rid, root, selected_models)
        return await self._merge_workers(req, detail, rid, root, context)

    async def _spawn_workers(self, req, detail, rid, root, selected_models):
        sid=detail.session.session_id; main=pathlib.Path(root); workers_root=main.parent/"workers"
        base=await init_repo(str(main)); await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.repo_initialized,commit_sha=base,message="repo initialized"))
        pi_cmd=req.metadata.get("fake_pi_command") or os.environ.get("NEXUSSY_PI_COMMAND") or self.config.pi.command
        cfg=self.config.model_copy(deep=True); cfg.pi.command=pi_cmd; cfg.pi.args=req.metadata.get("fake_pi_args") or cfg.pi.args
        requested_roles=req.metadata.get("worker_roles") or ["backend","frontend"]
        roles=[]
        for raw in requested_roles:
            try: roles.append(WorkerRole(raw))
            except Exception: pass
        roles=roles[: max(1, min(self.config.swarm.max_workers, self.config.swarm.default_worker_count if not req.metadata.get("worker_roles") else len(roles)))] or [WorkerRole.backend]
        orch_model=self.config.stages.develop.orchestrator_model or selected_models.get("develop") or self.config.providers.default_model
        orch=Worker(worker_id=f"orchestrator-{uuid4().hex[:6]}",run_id=rid,role=WorkerRole.orchestrator,status=WorkerStatus.running,task_id=f"task-{uuid4().hex[:6]}",task_title="Orchestrate develop run",worktree_path=str(main),branch_name="main",model=orch_model)
        await self._persist_worker(orch); await self.emit(SSEEventType.worker_spawned,sid,rid,orch)
        return {"sid":sid,"main":main,"workers_root":workers_root,"artifacts_dir":main/".nexussy"/"artifacts","base":base,"cfg":cfg,"roles":roles,"orch":orch,"selected_models":selected_models}

    async def _merge_workers(self, req, detail, rid, root, context):
        sid=context["sid"]; main=context["main"]; artifacts_dir=context["artifacts_dir"]; base=context["base"]; roles=context["roles"]; orch=context["orch"]
        workers=[orch]; merged=[]
        # Workers run concurrently; merge state is collected locally and updated serially below.
        worker_results=await asyncio.gather(*[self._run_single_worker(req, detail, rid, root, role, idx, context) for idx, role in enumerate(roles, start=1)], return_exceptions=True)
        for result in worker_results:
            if isinstance(result, Exception): raise result
            merge_result=await self._merge_single_worker(result, req, detail, rid, root, context, workers, merged)
            workers.append(merge_result.worker); merged.append(merge_result.worker_id)
        await prune_worktrees(str(main)); manifest=await extract_changed_files(str(main),base,str(artifacts_dir/"changed-files"),rid)
        orch.status=WorkerStatus.finished; await self._persist_worker(orch); await self.emit(SSEEventType.worker_status,sid,rid,orch)
        merge_report=MergeReport(run_id=rid,base_commit=base,merge_commit=manifest.merge_commit,merged_workers=merged,passed=True)
        return [await self._save_art(rid,sid,root,"develop_report",DevelopReport(run_id=rid,passed=True,workers=workers,tasks_total=len(workers),tasks_passed=len(workers)).model_dump_json(indent=2)), await self._save_art(rid,sid,root,"merge_report",merge_report.model_dump_json(indent=2)), await self._save_art(rid,sid,root,"changed_files",manifest.model_dump_json(indent=2))]

    async def _run_single_worker(self, req, detail, rid, root, role, idx, context):
        sid=context["sid"]; main=context["main"]; workers_root=context["workers_root"]; base=context["base"]; cfg=context["cfg"]; selected_models=context["selected_models"]
        wid=f"{role.value}-{uuid4().hex[:6]}"
        async with self.git_lock:
            wt, branch=await create_worktree(str(main), str(workers_root), wid, base)
        await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.worktree_created,worker_id=wid,branch_name=branch,message="worktree created"))
        worker=Worker(worker_id=wid,run_id=rid,role=role,status=WorkerStatus.running,task_id=f"task-{uuid4().hex[:6]}",task_title=f"Develop task {idx}",worktree_path=wt,branch_name=branch,model=selected_models.get("develop") or self.config.stages.develop.model)
        await self._persist_worker(worker); await self.emit(SSEEventType.worker_spawned,sid,rid,worker)
        await self._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.running)
        await self.emit(SSEEventType.worker_task,sid,rid,WorkerTaskPayload(worker_id=worker.worker_id,task_id=worker.task_id,phase_number=idx,task_title=worker.task_title,status=WorkerTaskStatus.running))
        await self._run_worker_rpc(rid, sid, worker, idx, cfg, role, main, wt)
        if not [p for p in pathlib.Path(wt).glob("**/*") if ".git" not in p.parts]:
            pathlib.Path(wt, f"{role.value}.txt").write_text(f"{role.value} completed\n")
        commit=await commit_worker(wt, f"nexussy: {wid} {worker.task_id}")
        return {"worker":worker,"idx":idx,"wid":wid,"wt":wt,"branch":branch,"commit":commit}

    async def _run_worker_rpc(self, rid, sid, worker, idx, cfg, role, main, wt, _depth: int = 0):
        if _depth >= 3:
            raise RuntimeError("worker RPC max resume depth exceeded")
        rpc=await spawn_pi_worker(cfg,rid,worker.worker_id,role.value,str(main),wt)
        self.active_worker_rpcs.setdefault(rid,[]).append(rpc)
        req_id=await rpc.request(worker.task_title, "nexussy develop task")
        was_paused_on_timeout=False
        try: await rpc.wait_response(req_id, self.config.swarm.worker_task_timeout_s)
        except TimeoutError:
            # Capture pause state before cleanup can race with an external resume.
            was_paused_on_timeout=bool(self.paused.get(rid))
            logger.warning("worker %s timed out for run %s", worker.worker_id, rid)
            if not was_paused_on_timeout: raise
        finally:
            for frame in rpc.frames:
                await self.emit(SSEEventType.worker_stream,sid,rid,frame.payload)
            await rpc.stop(self.config.pi.shutdown_timeout_s)
            if rpc in self.active_worker_rpcs.get(rid,[]): self.active_worker_rpcs[rid].remove(rpc)
        if was_paused_on_timeout:
            worker.status=WorkerStatus.paused; await self._persist_worker(worker); await self.emit(SSEEventType.worker_status,sid,rid,worker)
            await self._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.queued)
            await self.emit(SSEEventType.worker_task,sid,rid,WorkerTaskPayload(worker_id=worker.worker_id,task_id=worker.task_id,phase_number=idx,task_title=worker.task_title,status=WorkerTaskStatus.queued))
            ck=await save_checkpoint(self.db, rid, StageName.develop, f".nexussy/checkpoints/develop-{worker.task_id}.json", sha256_text(worker.task_id or worker.worker_id))
            await self.emit(SSEEventType.checkpoint_saved,sid,rid,ck)
            while self.paused.get(rid): await asyncio.sleep(.05)
            worker.status=WorkerStatus.running; await self._persist_worker(worker); await self.emit(SSEEventType.worker_status,sid,rid,worker)
            await self._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.running)
            await self.emit(SSEEventType.worker_task,sid,rid,WorkerTaskPayload(worker_id=worker.worker_id,task_id=worker.task_id,phase_number=idx,task_title=worker.task_title,status=WorkerTaskStatus.running))
            await self._run_worker_rpc(rid, sid, worker, idx, cfg, role, main, wt, _depth=_depth+1)

    async def _merge_single_worker(self, result, req, detail, rid, root, context, workers, merged) -> WorkerMergeResult:
        sid=context["sid"]; main=context["main"]; base=context["base"]; roles=context["roles"]
        worker=result["worker"]; idx=result["idx"]; wid=result["wid"]; wt=result["wt"]; branch=result["branch"]; commit=result["commit"]
        await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.merge_started,worker_id=wid,branch_name=branch,commit_sha=commit,message="merge started"))
        mr=await merge_no_ff(str(main), branch)
        if not mr.passed:
            await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.merge_conflict,worker_id=wid,branch_name=branch,paths=mr.conflicts,message="merge conflict"))
            await self._save_art(rid,sid,root,"merge_report",MergeReport(run_id=rid,base_commit=base,merged_workers=merged,conflicts=mr.conflicts,passed=False).model_dump_json(indent=2))
            await self._save_art(rid,sid,root,"develop_report",DevelopReport(run_id=rid,passed=False,workers=workers+[worker],tasks_total=len(roles),tasks_passed=len(merged),tasks_failed=1).model_dump_json(indent=2))
            raise RuntimeError("merge conflict")
        await remove_worktree(str(main), wt, branch); await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.worktree_removed,worker_id=wid,branch_name=branch,message="worktree removed"))
        worker.status=WorkerStatus.finished; await self._persist_worker(worker); await self.emit(SSEEventType.worker_status,sid,rid,worker)
        await self._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.passed)
        await self.emit(SSEEventType.worker_task,sid,rid,WorkerTaskPayload(worker_id=worker.worker_id,task_id=worker.task_id,phase_number=idx,task_title=worker.task_title,status=WorkerTaskStatus.passed))
        return WorkerMergeResult(worker=worker, worker_id=wid)

    async def _persist_worker(self, w: Worker):
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO workers VALUES(?,?,?,?,?,?,?,?,?,?,?)",(w.worker_id,w.run_id,w.role,w.status,w.task_id,w.worktree_path,w.branch_name,w.pid,w.usage.model_dump_json(),w.last_error.model_dump_json() if w.last_error else None,w.model_dump_json())))

    async def _persist_worker_task(self, run_id: str, worker_id: str, task_id: str, phase_number: int|None, title: str, status: WorkerTaskStatus):
        now=now_utc().isoformat(); status_value=status.value if hasattr(status,"value") else status
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO worker_tasks VALUES(?,?,?,?,?,?,COALESCE((SELECT created_at FROM worker_tasks WHERE task_id=?),?),?)",(task_id,run_id,worker_id,phase_number,title,status_value,task_id,now,now)))

class ProviderStartError(Exception):
    def __init__(self, error: ErrorResponse):
        self.error = error
        super().__init__(error.message)
