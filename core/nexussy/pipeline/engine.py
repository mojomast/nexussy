from __future__ import annotations
import asyncio, json, logging, pathlib, shutil, hashlib, subprocess
from datetime import datetime, timedelta; from uuid import uuid4
from nexussy.api.schemas import ArtifactRef, ArtifactUpdatedPayload, DonePayload, ErrorCode, ErrorResponse, EventEnvelope, InterviewArtifact, InterviewQuestionAnswer, JsonValue, PausePayload, PipelineStartRequest, RunStartResponse, RunStatus, RunSummary, SSEEventType, SessionCreateRequest, SessionDetail, SessionSummary, StageName, StageRunStatus, StageStatusSchema, StageTransitionPayload, TokenUsage, ToolCallPayload, ToolName, ToolOutputPayload, Worker, WorkerTaskStatus
from nexussy.artifacts.store import safe_write, artifact_path
from nexussy.audit import write_audit
from nexussy.checkpoint import STAGE_ORDER, latest_checkpoint, resume_from_checkpoint, save_checkpoint
from nexussy.providers import active_rate_limit, complete, effective_secret_env, mock_requested, model_available, provider_error_for_model, provider_for_model, select_stage_model
from nexussy.session import SessionStatus, now_utc, transition_session_status
from nexussy.swarm.locks import write_requires_lock
from nexussy.swarm.pi_rpc import spawn_pi_worker
from nexussy.swarm.roles import enforce_tool
from nexussy.pipeline.helpers import ProviderStartError, complexity, slugify, validate_existing_repo_path
from nexussy.pipeline.stages import design, develop, interview, plan, review, validate
logger = logging.getLogger(__name__); STAGES=[StageName(s) for s in STAGE_ORDER]
def _rate_limited_error(provider: str, model: str, limited) -> ErrorResponse: return ErrorResponse(error_code=ErrorCode.rate_limited, message="provider rate limited", details={"provider":provider,"model":model,"reset_at":limited["reset_at"]}, retryable=True)
class Engine:
    def __init__(self, db, config):
        self.db=db; self.config=config; self.queues:dict[str,set[asyncio.Queue]]={}; self.tasks={}; self.paused={}; self.interview_waiters:dict[str,asyncio.Future]={}; self.interview_questions:dict[str,list[InterviewQuestionAnswer]]={}; self.session_runs:dict[str,str]={}; self.active_worker_rpcs:dict[str,list]={}; self.blocked_previous_status:dict[str,str]={}; self.git_lock=asyncio.Lock(); self.provider_env_cache:dict|None=None; self._run_usage:dict[str,TokenUsage]={}
    def invalidate_provider_cache(self): self.provider_env_cache=None
    async def restore_interview_state(self) -> None:
        rows = await self.db.read("SELECT run_id, session_id FROM runs WHERE status = 'running'", ())
        for row in rows:
            rid = row["run_id"]; sid = row["session_id"]
            cps = await self.db.read("SELECT path FROM checkpoints WHERE run_id = ? AND stage = 'interview'", (rid,))
            if cps and rid not in self.tasks:
                logger.warning("Run %s found in 'running' state on startup with no active task - marking as failed. Resubmit via POST /pipeline/start with resume_run_id=%s", rid, rid)
                await self.db.write(lambda con, r=rid: con.execute("UPDATE runs SET status='failed', finished_at=? WHERE run_id=?", (now_utc().isoformat(), r)))
                await transition_session_status(self.db, sid, SessionStatus.failed)
    async def _persist_event(self, env: EventEnvelope):
        typ = env.type.value if hasattr(env.type, "value") else env.type
        def tx(con):
            row=con.execute("INSERT INTO events(event_id, run_id, sequence, type, payload_json, created_at) VALUES(?, ?, (SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?), ?, ?, ?) RETURNING sequence", (env.event_id, env.run_id, env.run_id, typ, json.dumps(env.model_dump(mode="json")), env.ts.isoformat())).fetchone()
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
        if req.existing_repo_path:
            src=validate_existing_repo_path(req.existing_repo_path)
            result=subprocess.run(["git", "-C", str(src), "rev-parse", "--git-dir"], capture_output=True, text=True)
            if result.returncode == 0:
                shutil.copytree(src, main, dirs_exist_ok=True, symlinks=False)
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
                raise ProviderStartError(_rate_limited_error(provider, model, limited))
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
                stage_value=checkpoint.stage.value if hasattr(checkpoint.stage, 'value') else checkpoint.stage
                next_index=STAGE_ORDER.index(stage_value)
                if not (stage_value == StageName.interview.value and checkpoint.path.endswith("interview-questions.json")):
                    next_index=min(next_index+1, len(STAGES)-1)
                candidate=STAGES[next_index]
                if STAGES.index(candidate) > STAGES.index(req.start_stage): start_stage=candidate
        effective_req=req.model_copy(update={"start_stage":start_stage})
        detail=await self.create_session(effective_req); rid=effective_req.resume_run_id or str(uuid4()); now=now_utc();
        self._run_usage[rid]=TokenUsage()
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
                ck=await save_checkpoint(self.db, run.run_id, st, f".nexussy/checkpoints/{st.value}.json", content=await self._checkpoint_content_for_stage(run.run_id, st, made))
                await self.emit(SSEEventType.checkpoint_saved, detail.session.session_id, run.run_id, ck); prev=st; i += 1
                if st == StageName.plan: review_feedback_for_plan = ""
            usage=self._run_usage.get(run.run_id, TokenUsage())
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=?, current_stage=?, usage_json=? WHERE run_id=?",("passed",now_utc().isoformat(),prev.value if prev else None,usage.model_dump_json(),run.run_id)))
            await transition_session_status(self.db, detail.session.session_id, SessionStatus.passed)
            write_audit(self.config.home_dir, "pipeline_stop", run_id=run.run_id, session_id=detail.session.session_id, status="passed")
            await self.emit(SSEEventType.done, detail.session.session_id, run.run_id, DonePayload(final_status=RunStatus.passed,summary="pipeline completed",artifacts=artifacts,usage=usage))
        except asyncio.CancelledError:
            fut=self.interview_waiters.pop(detail.session.session_id, None)
            if fut and not fut.done(): fut.cancel()
            self.interview_questions.pop(detail.session.session_id, None)
            usage=self._run_usage.get(run.run_id, TokenUsage())
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=?, usage_json=? WHERE run_id=?",("cancelled",now_utc().isoformat(),usage.model_dump_json(),run.run_id)))
            await transition_session_status(self.db, detail.session.session_id, SessionStatus.cancelled)
            write_audit(self.config.home_dir, "pipeline_cancel", run_id=run.run_id, session_id=detail.session.session_id, status="cancelled")
            raise
        except Exception as e:
            er=ErrorResponse(error_code=ErrorCode.stage_failed,message=str(e),retryable=False)
            self.paused.pop(run.run_id, None)
            logger.exception("pipeline run %s failed at stage %s: %s", run.run_id, prev, e)
            usage=self._run_usage.get(run.run_id, TokenUsage())
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=?, usage_json=? WHERE run_id=?",("failed",now_utc().isoformat(),usage.model_dump_json(),run.run_id)))
            await transition_session_status(self.db, detail.session.session_id, SessionStatus.failed)
            write_audit(self.config.home_dir, "pipeline_stop", run_id=run.run_id, session_id=detail.session.session_id, status="failed")
            await self.emit(SSEEventType.pipeline_error, detail.session.session_id, run.run_id, er)
            await self.emit(SSEEventType.done, detail.session.session_id, run.run_id, DonePayload(final_status=RunStatus.failed,summary="pipeline failed",artifacts=artifacts,usage=usage,error=er))
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
        call_id=str(uuid4())
        stage=StageName.develop
        await self.emit(SSEEventType.tool_call,sid,run_id,ToolCallPayload(call_id=call_id,stage=stage,tool_name=tool_value,arguments=arguments,worker_id=worker_id))
        try:
            path=arguments.get("path") if isinstance(arguments, dict) else None
            enforce_tool(worker.role, tool, path)
            if tool in {ToolName.write_file, ToolName.edit_file} and path:
                await write_requires_lock(self.db, run_id, str(path), worker_id)
            payload=ToolOutputPayload(call_id=call_id,stage=stage,success=True,result_text="{}",worker_id=worker_id)
        except PermissionError as e:
            payload=ToolOutputPayload(call_id=call_id,stage=stage,success=False,error=str(e) or "forbidden",worker_id=worker_id)
        await self.emit(SSEEventType.tool_output,sid,run_id,payload)
        return payload.model_dump(mode="json")
    async def _provider_text(self, st: StageName, sid: str, rid: str, prompt: str, selected_models, allow_mock: bool) -> str:
        model = (selected_models or {}).get(st.value) or self.config.providers.default_model
        stage_cfg = getattr(self.config.stages, st.value, None)
        max_retries = max(1, int(getattr(stage_cfg, "max_retries", self.config.providers.max_retries) or self.config.providers.max_retries or 1))
        last_error = None
        for attempt in range(max_retries):
            try:
                provider = provider_for_model(model)
                limited = await active_rate_limit(self.db, provider, model)
                if limited:
                    raise ProviderStartError(_rate_limited_error(provider, model, limited))
                if self.provider_env_cache is None:
                    self.provider_env_cache = effective_secret_env()
                result = await complete(st.value, prompt, model, allow_mock=allow_mock, timeout_s=self.config.providers.request_timeout_s, _env=self.provider_env_cache, db=self.db)
                break
            except Exception as e:
                last_error = e
                if attempt + 1 >= max_retries:
                    limited = await active_rate_limit(self.db, provider_for_model(model), model)
                    if limited:
                        raise ProviderStartError(_rate_limited_error(provider_for_model(model), model, limited)) from e
                    if getattr(e, "status_code", None) == 429 or "429" in str(e) or "rate limit" in str(e).lower():
                        raise ProviderStartError(ErrorResponse(error_code=ErrorCode.rate_limited,message="provider rate limited",details={"provider":provider_for_model(model),"model":model,"reset_at":(now_utc()+timedelta(seconds=60)).isoformat()},retryable=True)) from e
                    raise
                await asyncio.sleep((self.config.providers.retry_base_ms / 1000) * (2 ** attempt))
        else:
            raise last_error or RuntimeError("provider failed")
        usage = TokenUsage(**result.usage)
        self._accumulate_usage(rid, usage)
        await self.emit(SSEEventType.cost_update, sid, rid, usage)
        return result.text
    def _accumulate_usage(self, run_id: str, usage: TokenUsage) -> None:
        total=self._run_usage.get(run_id, TokenUsage())
        self._run_usage[run_id]=TokenUsage(input_tokens=total.input_tokens + usage.input_tokens, output_tokens=total.output_tokens + usage.output_tokens, cache_read_tokens=total.cache_read_tokens + usage.cache_read_tokens, cache_write_tokens=total.cache_write_tokens + usage.cache_write_tokens, cost_usd=total.cost_usd + usage.cost_usd, provider=usage.provider or total.provider, model=usage.model or total.model)
    async def _update_stage_status(self, run_id: str, stage: StageName, status: str|StageRunStatus, *, attempt: int|None=None, started_at: datetime|None=None, finished_at: datetime|None=None, error: ErrorResponse|None=None):
        status_value=status.value if hasattr(status,"value") else status
        await self.db.write(lambda con: con.execute("UPDATE stage_runs SET status=?,attempt=COALESCE(?,attempt),started_at=COALESCE(?,started_at),finished_at=COALESCE(?,finished_at),error_json=? WHERE run_id=? AND stage=?", (status_value,attempt,started_at.isoformat() if started_at else None,finished_at.isoformat() if finished_at else None,error.model_dump_json() if error else None,run_id,stage.value)))
    async def _latest_artifact_text(self, run_id: str, kind: str) -> str:
        rows=await self.db.read("SELECT content_text FROM artifacts WHERE run_id=? AND kind=? ORDER BY updated_at DESC LIMIT 1",(run_id,kind))
        return rows[0]["content_text"] if rows else ""
    async def _checkpoint_content_for_stage(self, run_id: str, stage: StageName, made: list[ArtifactRef]) -> str | None:
        primary={
            StageName.interview:"interview",
            StageName.design:"design_draft",
            StageName.validate:"validated_design",
            StageName.plan:"devplan",
            StageName.review:"review_report",
            StageName.develop:"develop_report",
        }.get(stage)
        if primary:
            text=await self._latest_artifact_text(run_id, primary)
            if text:
                return text
        if made:
            refs=[{"kind":ref.kind,"path":ref.path,"sha256":ref.sha256,"bytes":ref.bytes,"phase_number":ref.phase_number} for ref in made]
            return json.dumps(refs, sort_keys=True, separators=(",",":"))
        return None
    async def _latest_report_passed(self, run_id: str, kind: str, default: bool) -> bool:
        text=await self._latest_artifact_text(run_id, kind)
        if not text: return default
        try: data=json.loads(text)
        except Exception: return default
        return bool(data.get("passed", default)) if isinstance(data, dict) else default
    async def _latest_review_feedback(self, run_id: str) -> str:
        text=await self._latest_artifact_text(run_id, "review_report")
        if not text: return ""
        try: data=json.loads(text)
        except Exception: return ""
        return str(data.get("feedback_for_plan_stage") or "") if isinstance(data, dict) else ""
    async def _latest_interview_artifact(self, run_id: str) -> InterviewArtifact|None:
        rows=await self.db.read("SELECT content_text FROM artifacts WHERE run_id=? AND kind='interview' ORDER BY updated_at DESC LIMIT 1",(run_id,))
        return InterviewArtifact.model_validate_json(rows[0]["content_text"]) if rows else None
    async def submit_interview_answers(self, session_id: str, answers: dict[str,str]) -> InterviewArtifact:
        rid=self.session_runs.get(session_id)
        if not rid:
            rows=await self.db.read("SELECT run_id FROM runs WHERE session_id=? ORDER BY started_at DESC LIMIT 1",(session_id,)); rid=rows[0]["run_id"] if rows else None
        if not rid: raise KeyError("run")
        current=None; questions=self.interview_questions.get(session_id)
        if not questions: current=await self._latest_interview_artifact(rid); questions=current.questions if current else []
        missing=[q.question_id for q in questions if not answers.get(q.question_id, "").strip()]
        if missing: raise ValueError([{"loc":["body","answers"],"msg":"missing interview answers","type":"value_error","ctx":{"missing":missing}}])
        answered=[InterviewQuestionAnswer(question_id=q.question_id,question=q.question,answer=answers[q.question_id].strip(),source="user") for q in questions]
        fut=self.interview_waiters.get(session_id)
        if fut and not fut.done(): fut.set_result(answered)
        self.paused.pop(rid,None)
        await self.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("running",rid)))
        await transition_session_status(self.db, session_id, SessionStatus.running)
        await self.emit(SSEEventType.pause_state_changed,session_id,rid,PausePayload(paused=False,reason="interview answered"))
        current=current or await self._latest_interview_artifact(rid)
        return InterviewArtifact(project_name=current.project_name if current else "pending",project_slug=current.project_slug if current else "pending",description=current.description if current else "pending",questions=answered,requirements=[a.answer for a in answered])
    async def _artifacts_for_stage(self, st, req, detail, rid, cp, root, selected_models=None, allow_mock=False, review_feedback_for_plan: str=""):
        handler=self._STAGE_HANDLERS.get(st)
        if handler: return await handler(self, req, detail, rid, cp, root, selected_models or {}, allow_mock, review_feedback_for_plan=review_feedback_for_plan)
        return []
    async def _persist_worker(self, w: Worker):
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO workers VALUES(?,?,?,?,?,?,?,?,?,?,?)",(w.worker_id,w.run_id,w.role,w.status,w.task_id,w.worktree_path,w.branch_name,w.pid,w.usage.model_dump_json(),w.last_error.model_dump_json() if w.last_error else None,w.model_dump_json())))
    async def _persist_worker_task(self, run_id: str, worker_id: str, task_id: str, phase_number: int|None, title: str, status: WorkerTaskStatus):
        now=now_utc().isoformat(); status_value=status.value if hasattr(status,"value") else status; await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO worker_tasks VALUES(?,?,?,?,?,?,COALESCE((SELECT created_at FROM worker_tasks WHERE task_id=?),?),?)",(task_id,run_id,worker_id,phase_number,title,status_value,task_id,now,now)))
    async def _run_worker_rpc(self, *args, **kwargs):
        return await develop.run_worker_rpc(self, *args, spawn_fn=kwargs.pop("spawn_fn", spawn_pi_worker), **kwargs)
Engine._STAGE_HANDLERS = {StageName.interview: lambda engine, *a, **kw: interview.run(engine, *a, **kw), StageName.design: lambda engine, *a, **kw: design.run(engine, *a, **kw), StageName.validate: lambda engine, *a, **kw: validate.run(engine, *a, **kw), StageName.plan: lambda engine, *a, **kw: plan.run(engine, *a, **kw), StageName.review: lambda engine, *a, **kw: review.run(engine, *a, **kw), StageName.develop: lambda engine, *a, **kw: develop.run(engine, *a, spawn_fn=kw.pop("spawn_fn", spawn_pi_worker), **kw)}
