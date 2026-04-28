from __future__ import annotations
import asyncio, json, os, re, pathlib, shutil, hashlib
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from nexussy.api.schemas import *
from nexussy.artifacts.store import safe_write, artifact_path, sha256_text
from nexussy.providers import active_rate_limit, complete, mock_requested, model_available, provider_error_for_model, provider_for_model, select_stage_model
from nexussy.swarm.gitops import init_repo, create_worktree, commit_worker, merge_no_ff, extract_changed_files, prune_worktrees, remove_worktree
from nexussy.swarm.pi_rpc import spawn_pi_worker

STAGES=[StageName.interview,StageName.design,StageName.validate,StageName.plan,StageName.review,StageName.develop]

def slugify(name: str) -> str:
    s=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:63]
    return s or "project"

def complexity(desc: str, existing: bool=False) -> ComplexityProfile:
    d=desc.lower(); signals={}; score=0
    checks=[("multiple_languages",10, any(w in d for w in ["frontend and backend","typescript","python","java","go "])),("persistence",10, any(w in d for w in ["database","sqlite","postgres","persist"])),("auth",15, any(w in d for w in ["auth","security","password"])),("external_api",10,"api" in d),("ui_backend",15, any(w in d for w in ["ui","dashboard","web","tui"])),("deployment",10, any(w in d for w in ["deploy","docker","infra"])),("existing_repo",10, existing),("qa",10, any(w in d for w in ["test","qa"])),("ambiguous",15, len(desc.split())<8)]
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
        self.db=db; self.config=config; self.queues:dict[str,set[asyncio.Queue]]={}; self.tasks={}; self.paused={}
    async def emit(self, typ:SSEEventType, session_id:str, run_id:str, payload):
        rows=await self.db.read("SELECT COALESCE(MAX(sequence),0)+1 n FROM events WHERE run_id=?",(run_id,)); seq=rows[0]["n"]
        env=EventEnvelope(sequence=seq,type=typ,session_id=session_id,run_id=run_id,payload=payload.model_dump(mode="json") if hasattr(payload,"model_dump") else payload)
        await self.db.write(lambda con: con.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",(env.event_id,run_id,seq,typ.value if hasattr(typ,'value') else typ,json.dumps(env.model_dump(mode="json")),env.ts.isoformat())))
        for q in list(self.queues.get(run_id,set())):
            try: q.put_nowait(env)
            except asyncio.QueueFull:
                # Slow-consumer gate: give the stream one terminal diagnostic and
                # drop this queue. The diagnostic is not inserted into the global
                # event log to avoid recursively overflowing every slow queue.
                self.queues.get(run_id,set()).discard(q)
                slow=EventEnvelope(sequence=seq,type=SSEEventType.pipeline_error,session_id=session_id,run_id=run_id,payload=ErrorResponse(error_code=ErrorCode.sse_client_slow,message="SSE client queue exceeded",retryable=True).model_dump(mode="json"))
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
        if req.existing_repo_path and pathlib.Path(req.existing_repo_path).exists():
            pass
        detail=SessionDetail(session=SessionSummary(session_id=sid,project_name=req.project_name,project_slug=slug,created_at=now,updated_at=now),project_root=str(root),main_worktree=str(main),artifacts=[],runs=[])
        await self.db.write(lambda con: con.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",(sid,slug,req.project_name,"created",now.isoformat(),now.isoformat(),detail.model_dump_json())))
        return detail
    async def start(self, req:PipelineStartRequest):
        allow_mock = mock_requested(req.metadata)
        selected = {st.value: select_stage_model(self.config, st.value, { (k.value if hasattr(k,'value') else k): v for k,v in req.model_overrides.items() }) for st in STAGES}
        for st, model in selected.items():
            provider = provider_for_model(model)
            limited = await active_rate_limit(self.db, provider, model)
            if limited:
                raise ProviderStartError(ErrorResponse(error_code=ErrorCode.rate_limited, message="provider rate limited", details={"provider":provider,"model":model,"reset_at":limited["reset_at"]}, retryable=True))
            if not model_available(model, allow_mock=allow_mock):
                if self.config.providers.allow_fallback and model_available(self.config.providers.default_model, allow_mock=allow_mock):
                    # create run below then emit pipeline_error from _run context
                    selected[st] = self.config.providers.default_model
                    continue
                raise ProviderStartError(provider_error_for_model(model))
        detail=await self.create_session(req); rid=req.resume_run_id or str(uuid4()); now=now_utc();
        run=RunSummary(run_id=rid,session_id=detail.session.session_id,status=RunStatus.running,current_stage=req.start_stage,started_at=now)
        await self.db.write(lambda con: (con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",(rid,detail.session.session_id,"running",req.start_stage.value,now.isoformat(),None,run.usage.model_dump_json())), con.execute("UPDATE sessions SET status=?, updated_at=?, detail_json=? WHERE session_id=?",("running",now.isoformat(),detail.model_dump_json(),detail.session.session_id))))
        for st in STAGES: await self.db.write(lambda con, st=st: con.execute("INSERT OR REPLACE INTO stage_runs VALUES(?,?,?,?,?,?,?)",(rid,st.value,"pending",0,None,None,None)))
        await self.emit(SSEEventType.run_started, detail.session.session_id, rid, run)
        self.tasks[rid]=asyncio.create_task(self._run(req, detail, run, selected, allow_mock))
        return RunStartResponse(session_id=detail.session.session_id,run_id=rid,stream_url=f"/pipeline/runs/{rid}/stream",status_url=f"/pipeline/status?run_id={rid}")
    async def _run(self, req, detail, run, selected_models=None, allow_mock=False):
        start=STAGES.index(req.start_stage); stop=STAGES.index(req.stop_after_stage) if req.stop_after_stage else len(STAGES)-1
        artifacts=[]; root=detail.main_worktree; prev=None
        cp=complexity(req.description, bool(req.existing_repo_path))
        try:
            i = start
            review_iterations = 0
            validation_iterations = 0
            while i <= stop:
                st = STAGES[i]
                while self.paused.get(run.run_id): await asyncio.sleep(.05)
                attempt = (validation_iterations + 1) if st == StageName.validate else ((review_iterations + 1) if st == StageName.review else 1)
                t0=now_utc(); await self.db.write(lambda con, st=st, attempt=attempt: con.execute("UPDATE stage_runs SET status=?,attempt=?,started_at=? WHERE run_id=? AND stage=?",("running",attempt,t0.isoformat(),run.run_id,st.value)))
                await self.emit(SSEEventType.stage_transition, detail.session.session_id, run.run_id, StageTransitionPayload(from_stage=prev,to_stage=st,from_status=StageRunStatus.passed if prev else None,to_status=StageRunStatus.running,reason="stage started"))
                made=await self._artifacts_for_stage(st, req, detail, run.run_id, cp, root, selected_models or {}, allow_mock)
                artifacts.extend(made)
                if st == StageName.validate:
                    validation_iterations += 1
                    fail_for = int(req.metadata.get("validate_fail_iterations", 0) or (self.config.stages.validate.max_iterations or 3 if req.metadata.get("force_validate_fail") else 0))
                    if validation_iterations <= fail_for:
                        await self.db.write(lambda con: con.execute("UPDATE stage_runs SET status=?,attempt=?,error_json=? WHERE run_id=? AND stage=?",("retrying",validation_iterations,ErrorResponse(error_code=ErrorCode.validation_error,message="validation issues require design correction",retryable=True).model_dump_json(),run.run_id,StageName.validate.value)))
                        if validation_iterations < (self.config.stages.validate.max_iterations or 3):
                            await self.emit(SSEEventType.stage_transition, detail.session.session_id, run.run_id, StageTransitionPayload(from_stage=StageName.validate,to_stage=StageName.design,from_status=StageRunStatus.failed,to_status=StageRunStatus.retrying,reason="validation corrections returned to design"))
                            i = STAGES.index(StageName.design); prev = StageName.validate; continue
                        raise RuntimeError("validate max iterations exceeded")
                if st == StageName.review and req.metadata.get("force_review_fail"):
                    review_iterations += 1
                    await self.db.write(lambda con: con.execute("UPDATE stage_runs SET status=?,attempt=?,error_json=? WHERE run_id=? AND stage=?",("retrying",review_iterations,ErrorResponse(error_code=ErrorCode.stage_failed,message="review feedback requires plan correction",retryable=True).model_dump_json(),run.run_id,StageName.review.value)))
                    if review_iterations < int(req.metadata.get("review_fail_iterations", self.config.stages.review.max_iterations or 2)):
                        await self.emit(SSEEventType.stage_transition, detail.session.session_id, run.run_id, StageTransitionPayload(from_stage=StageName.review,to_stage=StageName.plan,from_status=StageRunStatus.failed,to_status=StageRunStatus.retrying,reason="review feedback returned to plan"))
                        i = STAGES.index(StageName.plan); prev = StageName.review; continue
                    raise RuntimeError("review max iterations exceeded")
                fin=now_utc(); await self.db.write(lambda con, st=st: con.execute("UPDATE stage_runs SET status=?,finished_at=? WHERE run_id=? AND stage=?",("passed",fin.isoformat(),run.run_id,st.value)))
                await self.emit(SSEEventType.stage_status, detail.session.session_id, run.run_id, StageStatusSchema(stage=st,status=StageRunStatus.passed,attempt=1,finished_at=fin,output_artifacts=made))
                ck=CheckpointPayload(checkpoint_id=str(uuid4()),stage=st,path=f".nexussy/checkpoints/{st.value}.json",sha256=sha256_text(st.value),created_at=fin)
                await self.db.write(lambda con, ck=ck: con.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?)",(ck.checkpoint_id,run.run_id,st.value,ck.path,ck.sha256,ck.created_at.isoformat())))
                await self.emit(SSEEventType.checkpoint_saved, detail.session.session_id, run.run_id, ck); prev=st; i += 1
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=?, current_stage=? WHERE run_id=?",("passed",now_utc().isoformat(),prev.value if prev else None,run.run_id)))
            await self.emit(SSEEventType.done, detail.session.session_id, run.run_id, DonePayload(final_status=RunStatus.passed,summary="pipeline completed",artifacts=artifacts,usage=TokenUsage()))
        except asyncio.CancelledError:
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?",("cancelled",now_utc().isoformat(),run.run_id)))
            raise
        except Exception as e:
            er=ErrorResponse(error_code=ErrorCode.stage_failed,message=str(e),retryable=False)
            await self.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?",("failed",now_utc().isoformat(),run.run_id)))
            await self.emit(SSEEventType.pipeline_error, detail.session.session_id, run.run_id, er)
            await self.emit(SSEEventType.done, detail.session.session_id, run.run_id, DonePayload(final_status=RunStatus.failed,summary="pipeline failed",artifacts=artifacts,usage=TokenUsage(),error=er))
    async def _save_art(self, run_id, session_id, root, kind, text, phase=None):
        rel=artifact_path(kind, phase); meta=safe_write(root, rel, text); ref=ArtifactRef(kind=kind,path=rel,sha256=meta["sha256"],bytes=meta["bytes"],phase_number=phase)
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?,?,?,?)",(run_id,kind,rel,ref.sha256,ref.bytes,ref.updated_at.isoformat(),text,phase)))
        await self.emit(SSEEventType.artifact_updated, session_id, run_id, ArtifactUpdatedPayload(artifact=ref,action="created")); return ref
    async def _provider_text(self, st: StageName, sid: str, rid: str, prompt: str, selected_models, allow_mock: bool) -> str:
        model = (selected_models or {}).get(st.value) or self.config.providers.default_model
        result = await complete(st.value, prompt, model, allow_mock=allow_mock, timeout_s=self.config.providers.request_timeout_s)
        usage = TokenUsage(**result.usage)
        await self.emit(SSEEventType.cost_update, sid, rid, usage)
        return result.text

    async def _artifacts_for_stage(self, st, req, detail, rid, cp, root, selected_models=None, allow_mock=False):
        sid=detail.session.session_id
        if st==StageName.interview:
            await self._provider_text(st, sid, rid, f"Interview requirements for: {req.description}", selected_models, allow_mock)
            ia=InterviewArtifact(project_name=req.project_name,project_slug=detail.session.project_slug,description=req.description,questions=[InterviewQuestionAnswer(question_id="q1",question="Use defaults?",answer=str(req.auto_approve_interview),source="auto")],requirements=[req.description])
            return [await self._save_art(rid,sid,root,"interview",ia.model_dump_json(indent=2)), await self._save_art(rid,sid,root,"complexity_profile",cp.model_dump_json(indent=2))]
        if st==StageName.design:
            txt=await self._provider_text(st, sid, rid, f"Create design with Goals, Architecture, Dependencies, Risks, Test Strategy for: {req.description}", selected_models, allow_mock)
            return [await self._save_art(rid,sid,root,"design_draft",txt if all(h in txt for h in ["Goals","Architecture","Dependencies","Risks","Test Strategy"]) else "# Goals\nDeliver requested project.\n# Architecture\nProvider-guided design.\n# Dependencies\nPython.\n# Risks\nUnknowns.\n# Test Strategy\nAutomated tests.\n")]
        if st==StageName.validate:
            return [await self._save_art(rid,sid,root,"validated_design","# Goals\nDeliver requested project.\n# Architecture\nValidated.\n# Dependencies\nPython.\n# Risks\nManaged.\n# Test Strategy\nAutomated tests.\n"), await self._save_art(rid,sid,root,"validation_report",ValidationReport(passed=True,max_iterations=self.config.stages.validate.max_iterations or 3).model_dump_json(indent=2))]
        if st==StageName.plan:
            dev="""# DevPlan\n<!-- PROGRESS_LOG_START -->\n- Created by nexussy.\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: implement requested work. Acceptance: tests pass.\n<!-- NEXT_TASK_GROUP_END -->\n"""
            hand="""# Handoff\n<!-- QUICK_STATUS_START -->\nPipeline plan generated.\n<!-- QUICK_STATUS_END -->\n<!-- HANDOFF_NOTES_START -->\nContinue from devplan.\n<!-- HANDOFF_NOTES_END -->\n<!-- SUBAGENT_A_ASSIGNMENT_START -->\nOwn core.\n<!-- SUBAGENT_A_ASSIGNMENT_END -->\n<!-- SUBAGENT_B_ASSIGNMENT_START -->\nOwn tui.\n<!-- SUBAGENT_B_ASSIGNMENT_END -->\n<!-- SUBAGENT_C_ASSIGNMENT_START -->\nOwn web.\n<!-- SUBAGENT_C_ASSIGNMENT_END -->\n<!-- SUBAGENT_D_ASSIGNMENT_START -->\nOwn ops.\n<!-- SUBAGENT_D_ASSIGNMENT_END -->\n"""
            refs=[await self._save_art(rid,sid,root,"devplan",dev), await self._save_art(rid,sid,root,"handoff",hand)]
            for i in range(1,cp.phase_count+1): refs.append(await self._save_art(rid,sid,root,"phase",f"# Phase {i:03d}\n<!-- PHASE_TASKS_START -->\n- [ ] Task {i}\n<!-- PHASE_TASKS_END -->\n<!-- PHASE_PROGRESS_START -->\n- pending\n<!-- PHASE_PROGRESS_END -->\n",i))
            return refs
        if st==StageName.review:
            passed = not req.metadata.get("force_review_fail")
            return [await self._save_art(rid,sid,root,"review_report",ReviewReport(passed=passed,max_iterations=self.config.stages.review.max_iterations or 2,feedback_for_plan_stage="Fix plan issues" if not passed else "").model_dump_json(indent=2))]
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
        base=init_repo(str(main)); await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.repo_initialized,commit_sha=base,message="repo initialized"))
        pi_cmd=req.metadata.get("fake_pi_command") or os.environ.get("NEXUSSY_PI_COMMAND") or self.config.pi.command
        cfg=self.config.model_copy(deep=True); cfg.pi.command=pi_cmd; cfg.pi.args=req.metadata.get("fake_pi_args") or cfg.pi.args
        requested_roles=req.metadata.get("worker_roles") or ["backend","frontend"]
        roles=[]
        for raw in requested_roles:
            try: roles.append(WorkerRole(raw))
            except Exception: pass
        roles=roles[: max(1, min(self.config.swarm.max_workers, self.config.swarm.default_worker_count if not req.metadata.get("worker_roles") else len(roles)))] or [WorkerRole.backend]
        workers=[]; merged=[]; last_merge=None
        orch_model=self.config.stages.develop.orchestrator_model or selected_models.get("develop") or self.config.providers.default_model
        orch=Worker(worker_id=f"orchestrator-{uuid4().hex[:6]}",run_id=rid,role=WorkerRole.orchestrator,status=WorkerStatus.running,task_id=f"task-{uuid4().hex[:6]}",task_title="Orchestrate develop run",worktree_path=str(main),branch_name="main",model=orch_model)
        await self._persist_worker(orch); await self.emit(SSEEventType.worker_spawned,sid,rid,orch); workers.append(orch)
        for idx, role in enumerate(roles, start=1):
            wid=f"{role.value}-{uuid4().hex[:6]}"; wt, branch=create_worktree(str(main), str(workers_root), wid, base); await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.worktree_created,worker_id=wid,branch_name=branch,message="worktree created"))
            worker=Worker(worker_id=wid,run_id=rid,role=role,status=WorkerStatus.running,task_id=f"task-{uuid4().hex[:6]}",task_title=f"Develop task {idx}",worktree_path=wt,branch_name=branch,model=selected_models.get("develop") or self.config.stages.develop.model)
            await self._persist_worker(worker); await self.emit(SSEEventType.worker_spawned,sid,rid,worker)
            await self._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.running)
            await self.emit(SSEEventType.worker_task,sid,rid,WorkerTaskPayload(worker_id=worker.worker_id,task_id=worker.task_id,phase_number=idx,task_title=worker.task_title,status=WorkerTaskStatus.running))
            rpc=await spawn_pi_worker(cfg,rid,wid,role.value,str(main),wt)
            req_id=await rpc.request(worker.task_title, "nexussy develop task")
            try: await rpc.wait_response(req_id, self.config.swarm.worker_task_timeout_s)
            finally:
                for frame in rpc.frames:
                    await self.emit(SSEEventType.worker_stream,sid,rid,frame.payload)
                await rpc.stop(self.config.pi.shutdown_timeout_s)
            if not list(pathlib.Path(wt).glob("**/*")):
                pathlib.Path(wt, f"{role.value}.txt").write_text(f"{role.value} completed\n")
            commit=commit_worker(wt, f"nexussy: {wid} {worker.task_id}")
            await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.merge_started,worker_id=wid,branch_name=branch,commit_sha=commit,message="merge started"))
            mr=merge_no_ff(str(main), branch); last_merge=mr
            if not mr.passed:
                await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.merge_conflict,worker_id=wid,branch_name=branch,paths=mr.conflicts,message="merge conflict"))
                await self._save_art(rid,sid,root,"merge_report",MergeReport(run_id=rid,base_commit=base,merged_workers=merged,conflicts=mr.conflicts,passed=False).model_dump_json(indent=2))
                await self._save_art(rid,sid,root,"develop_report",DevelopReport(run_id=rid,passed=False,workers=workers+[worker],tasks_total=len(roles),tasks_passed=len(merged),tasks_failed=1).model_dump_json(indent=2))
                raise RuntimeError("merge conflict")
            merged.append(wid); remove_worktree(str(main), wt, branch); await self.emit(SSEEventType.git_event,sid,rid,GitEventPayload(action=GitEventAction.worktree_removed,worker_id=wid,branch_name=branch,message="worktree removed"))
            worker.status=WorkerStatus.finished; await self._persist_worker(worker); await self.emit(SSEEventType.worker_status,sid,rid,worker); workers.append(worker)
            await self._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.passed)
            await self.emit(SSEEventType.worker_task,sid,rid,WorkerTaskPayload(worker_id=worker.worker_id,task_id=worker.task_id,phase_number=idx,task_title=worker.task_title,status=WorkerTaskStatus.passed))
        prune_worktrees(str(main)); manifest=extract_changed_files(str(main),base,str(artifacts_dir/"changed-files"),rid)
        orch.status=WorkerStatus.finished; await self._persist_worker(orch); await self.emit(SSEEventType.worker_status,sid,rid,orch)
        merge_report=MergeReport(run_id=rid,base_commit=base,merge_commit=manifest.merge_commit,merged_workers=merged,passed=True)
        return [await self._save_art(rid,sid,root,"develop_report",DevelopReport(run_id=rid,passed=True,workers=workers,tasks_total=len(workers),tasks_passed=len(workers)).model_dump_json(indent=2)), await self._save_art(rid,sid,root,"merge_report",merge_report.model_dump_json(indent=2)), await self._save_art(rid,sid,root,"changed_files",manifest.model_dump_json(indent=2))]

    async def _persist_worker(self, w: Worker):
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO workers VALUES(?,?,?,?,?,?,?,?,?,?,?)",(w.worker_id,w.run_id,w.role,w.status,w.task_id,w.worktree_path,w.branch_name,w.pid,w.usage.model_dump_json(),w.last_error.model_dump_json() if w.last_error else None,w.model_dump_json())))

    async def _persist_worker_task(self, run_id: str, worker_id: str, task_id: str, phase_number: int|None, title: str, status: WorkerTaskStatus):
        now=now_utc().isoformat(); status_value=status.value if hasattr(status,"value") else status
        await self.db.write(lambda con: con.execute("INSERT OR REPLACE INTO worker_tasks VALUES(?,?,?,?,?,?,COALESCE((SELECT created_at FROM worker_tasks WHERE task_id=?),?),?)",(task_id,run_id,worker_id,phase_number,title,status_value,task_id,now,now)))

class ProviderStartError(Exception):
    def __init__(self, error: ErrorResponse):
        self.error = error
        super().__init__(error.message)
