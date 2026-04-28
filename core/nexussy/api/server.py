from __future__ import annotations
import asyncio, json, logging, os, pathlib, shutil, yaml
from datetime import datetime, timezone
from uuid import uuid4
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
from pydantic import ValidationError
import uvicorn

from nexussy import __version__
from nexussy.api.schemas import (
    ArtifactContentResponse, ArtifactManifestResponse, ArtifactRef,
    AssistantReplyRequest, AssistantReplyResponse, Blocker, BlockerCreateRequest,
    BlockerResolveRequest, ControlResponse, ErrorCode, ErrorResponse,
    EventEnvelope, FileLock, GraphEdge, GraphNode, GraphResponse,
    HealthResponse, HeartbeatPayload, InterviewAnswerRequest, MemoryEntry,
    MemoryEntryCreateRequest, NexussyConfig, PausePayload, PipelineInjectRequest,
    PipelineStartRequest, PipelineStatusResponse, RunStatus, RunSummary,
    SSEEventType, SessionCreateRequest, SessionDetail, StageName,
    StageRunStatus, StageSkipRequest, StageStatusSchema, TokenUsage, Worker,
    WorkerAssignRequest, WorkerInjectRequest, WorkerSpawnRequest, WorkerStatus,
    WorkerTaskPayload, WorkerTaskStatus,
)
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.mcp import call_tool, list_tools
from nexussy.pipeline.engine import Engine
from nexussy.pipeline.engine import ProviderStartError
from nexussy.providers import active_rate_limit, complete, configured_providers, delete_secret, model_available, provider_error_for_model, provider_for_model, secret_names, secret_summary, set_secret
from nexussy.security import sanitize_path, sanitize_relative_path
from nexussy.session import now_utc

config=None; db=None; engine=None; _startup_lock: asyncio.Lock | None = None

def _get_startup_lock() -> asyncio.Lock:
    global _startup_lock
    if _startup_lock is None:
        _startup_lock = asyncio.Lock()
    return _startup_lock

def cors_origins_for(cfg):
    origins = cfg.security.cors_origins if cfg is not None else ["*"]
    if "*" in origins and os.environ.get("NEXUSSY_ENV", os.environ.get("ENV", "")).lower() == "production":
        if os.environ.get("NEXUSSY_ALLOW_WILDCARD_CORS") != "1":
            raise RuntimeError(
                "Wildcard CORS is not allowed in production. "
                "Set NEXUSSY_CORS_ORIGINS or NEXUSSY_ALLOW_WILDCARD_CORS=1 to override."
            )
        logging.getLogger(__name__).warning("wildcard CORS origin is enabled in production")
    return origins

async def _do_startup():
    global config, db, engine
    loaded=load_config()
    # Tests may pre-seed module state with an override config that points at the
    # same isolated database. Keep that explicit state; otherwise each lifespan
    # startup reloads from the current environment/config file.
    config=config if config is not None and config.database.global_path == loaded.database.global_path else loaded
    db=Database(config.database.global_path, config.database.busy_timeout_ms, config.database.write_retry_count, config.database.write_retry_base_ms)
    engine=Engine(db,config)
    await db.init()

async def startup():
    async with _get_startup_lock():
        await _do_startup()

def dump(model): return json.loads(model.model_dump_json()) if hasattr(model,"model_dump_json") else model
def err(code:ErrorCode, msg:str, status:int=400, details=None): return JSONResponse(dump(ErrorResponse(error_code=code,message=msg,details=details or {})), status_code=status)
def retry_after_header(error: ErrorResponse) -> dict[str, str]:
    if error.error_code != ErrorCode.rate_limited:
        return {}
    reset_at = error.details.get("reset_at") if isinstance(error.details, dict) else None
    if not reset_at:
        return {}
    try:
        dt = reset_at if isinstance(reset_at, datetime) else datetime.fromisoformat(str(reset_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return {"Retry-After": str(int(dt.timestamp()))}
    except (TypeError, ValueError, OverflowError):
        return {}
async def body(request, cls):
    try: return cls.model_validate(await request.json())
    except json.JSONDecodeError as e: raise ValueError([{"loc":["body"],"msg":"invalid JSON","type":"json_invalid","ctx":{"error":str(e)}}])
    except ValidationError as e: raise ValueError(e.errors())

async def ensure_db():
    async with _get_startup_lock():
        if config is None or db is None or engine is None:
            await _do_startup()
        await db.init()
async def auth(request):
    if request.url.path == "/health": return None
    if config is None or db is None or engine is None:
        await ensure_db()
    if config.auth.enabled and request.headers.get(config.auth.header_name) != os.environ.get(config.auth.api_key_env):
        return err(ErrorCode.unauthorized,"unauthorized",401)

async def endpoint(request, func):
    a=await auth(request)
    if a: return a
    try: await ensure_db(); return await func(request)
    except ValueError as e: return err(ErrorCode.validation_error,"validation error",400,{"errors":e.args[0] if e.args else str(e)})
    except ProviderStartError as e:
        code = e.error.error_code.value if hasattr(e.error.error_code, "value") else e.error.error_code
        return JSONResponse(dump(e.error), status_code=503 if code in ("provider_unavailable", "model_unavailable") else 429, headers=retry_after_header(e.error))
    except KeyError as e: return err(ErrorCode.not_found,"not found",404,{"key":str(e)})
    except Exception as e: return err(ErrorCode.internal_error,"internal error",500,{"error":str(e)})

async def health(request):
    async def inner(_):
        ok=True
        try: await ensure_db()
        except Exception: ok=False
        pi_available = config.pi.command == "pi" or shutil.which(config.pi.command) is not None
        return JSONResponse(dump(HealthResponse(version=__version__,db_ok=ok,providers_configured=configured_providers(service=config.security.keyring_service),pi_available=pi_available)))
    return await endpoint(request, inner)

async def sessions_create(request):
    async def inner(r): return JSONResponse(dump(await engine.create_session(await body(r,SessionCreateRequest))))
    return await endpoint(request, inner)
async def sessions_list(request):
    async def inner(r):
        lim=min(int(r.query_params.get("limit",50)),200); off=int(r.query_params.get("offset",0)); rows=await db.read("SELECT detail_json FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",(lim,off))
        return JSONResponse([dump(SessionDetail.model_validate_json(x["detail_json"]).session) for x in rows])
    return await endpoint(request, inner)
async def sessions_get(request):
    async def inner(r):
        rows=await db.read("SELECT detail_json FROM sessions WHERE session_id=?",(r.path_params["session_id"],));
        if not rows: raise KeyError("session")
        return JSONResponse(dump(SessionDetail.model_validate_json(rows[0]["detail_json"])))
    return await endpoint(request, inner)
async def sessions_delete(request):
    async def inner(r):
        sid=r.path_params["session_id"]; rows=await db.read("SELECT detail_json FROM sessions WHERE session_id=?",(sid,));
        if not rows: raise KeyError("session")
        detail=SessionDetail.model_validate_json(rows[0]["detail_json"])
        await db.write(lambda con: con.execute("DELETE FROM sessions WHERE session_id=?",(sid,)))
        if r.query_params.get("delete_files") == "true":
            project_root=sanitize_path(detail.project_root, [config.projects_dir])
            if project_root.exists():
                shutil.rmtree(project_root)
        return JSONResponse(dump(ControlResponse(run_id=sid,status=RunStatus.cancelled,message="session deleted")))
    return await endpoint(request, inner)

async def pipeline_start(request):
    async def inner(r): return JSONResponse(dump(await engine.start(await body(r,PipelineStartRequest))))
    return await endpoint(request, inner)

async def mcp_tools(request):
    async def inner(r): return JSONResponse({"tools": list_tools()})
    return await endpoint(request, inner)

async def mcp_call(request):
    async def inner(r):
        data=await r.json()
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            raise ValueError([{"loc":["body","name"],"msg":"name is required and must be a string","type":"value_error"}])
        args=data.get("arguments") or {}
        if not isinstance(args, dict):
            raise ValueError([{"loc":["body","arguments"],"msg":"arguments must be an object","type":"value_error"}])
        result=await call_tool(data["name"], args, engine=engine, db=db)
        return JSONResponse(dump(result))
    return await endpoint(request, inner)
async def interview_answer(request):
    async def inner(r):
        req=await body(r,InterviewAnswerRequest)
        return JSONResponse(dump(await engine.submit_interview_answers(r.path_params["session_id"], req.answers)))
    return await endpoint(request, inner)
async def status(request):
    async def inner(r):
        rid=r.query_params["run_id"]; runs=await db.read("SELECT * FROM runs WHERE run_id=?",(rid,));
        if not runs: raise KeyError("run")
        row=runs[0]; run=RunSummary(run_id=rid,session_id=row["session_id"],status=row["status"],current_stage=row["current_stage"],started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None)
        srows=await db.read("SELECT * FROM stage_runs WHERE run_id=? ORDER BY CASE stage WHEN 'interview' THEN 1 WHEN 'design' THEN 2 WHEN 'validate' THEN 3 WHEN 'plan' THEN 4 WHEN 'review' THEN 5 ELSE 6 END",(rid,))
        stages=[StageStatusSchema(stage=x["stage"],status=x["status"],attempt=x["attempt"] or 0,started_at=datetime.fromisoformat(x["started_at"]) if x["started_at"] else None,finished_at=datetime.fromisoformat(x["finished_at"]) if x["finished_at"] else None) for x in srows]
        w=[Worker.model_validate_json(x["worker_json"]) for x in await db.read("SELECT worker_json FROM workers WHERE run_id=?",(rid,))]
        blockers=[Blocker(blocker_id=x["blocker_id"],run_id=x["run_id"],worker_id=x["worker_id"],stage=x["stage"],severity=x["severity"],message=x["message"],resolved=bool(x["resolved"]),created_at=datetime.fromisoformat(x["created_at"]),resolved_at=datetime.fromisoformat(x["resolved_at"]) if x["resolved_at"] else None) for x in await db.read("SELECT * FROM blockers WHERE run_id=? AND resolved=0",(rid,))]
        return JSONResponse(dump(PipelineStatusResponse(run=run,stages=stages,workers=w,paused=bool(engine.paused.get(rid)),blockers=blockers)))
    return await endpoint(request, inner)

def sse_frame(e:EventEnvelope): return f"id: {e.event_id}\nevent: {e.type}\nretry: {config.sse.retry_ms}\ndata: {e.model_dump_json()}\n\n"
async def stream(request):
    a=await auth(request)
    if a: return a
    await ensure_db(); rid=request.path_params.get("run_id") or request.query_params.get("run_id")
    async def gen():
        for e in await engine.replay(rid, request.headers.get("last-event-id")):
            yield sse_frame(e)
        q=asyncio.Queue(maxsize=config.sse.client_queue_max_events); engine.queues.setdefault(rid,set()).add(q)
        try:
            while True:
                try:
                    e=await asyncio.wait_for(q.get(), timeout=config.sse.heartbeat_interval_s); yield sse_frame(e)
                    if e.type == SSEEventType.pipeline_error and isinstance(e.payload, dict) and e.payload.get("error_code") == ErrorCode.sse_client_slow.value: break
                except asyncio.TimeoutError:
                    rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(rid,)); sid=rows[0]["session_id"] if rows else "unknown"
                    hb=await engine.emit(SSEEventType.heartbeat,sid,rid,HeartbeatPayload()); yield sse_frame(hb)
        finally: engine.queues.get(rid,set()).discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream; charset=utf-8")

async def control_pause(request):
    async def inner(r):
        data=await r.json(); rid=data["run_id"]; reason=data.get("reason","user"); engine.paused[rid]=True
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(rid,));
        if not rows: raise KeyError("run")
        for rpc in list(engine.active_worker_rpcs.get(rid,[])):
            await rpc.stop(config.pi.shutdown_timeout_s)
        if rows: await engine.emit(SSEEventType.pause_state_changed,rows[0]["session_id"],rid,PausePayload(paused=True,reason=reason))
        await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("paused",rid)))
        return JSONResponse(dump(ControlResponse(run_id=rid,status=RunStatus.paused,message="paused")))
    return await endpoint(request, inner)
async def control_resume(request):
    async def inner(r):
        data=await r.json(); rid=data["run_id"]; engine.paused.pop(rid,None)
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(rid,));
        if not rows: raise KeyError("run")
        if rows: await engine.emit(SSEEventType.pause_state_changed,rows[0]["session_id"],rid,PausePayload(paused=False,reason="resume"))
        await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("running",rid)))
        return JSONResponse(dump(ControlResponse(run_id=rid,status=RunStatus.running,message="resumed")))
    return await endpoint(request, inner)
async def control_cancel(request):
    async def inner(r):
        data=await r.json(); rid=data["run_id"];
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(rid,));
        if not rows: raise KeyError("run")
        t=engine.tasks.get(rid)
        if t: t.cancel()
        await engine.emit(SSEEventType.pause_state_changed,rows[0]["session_id"],rid,PausePayload(paused=False,reason=data.get("reason","cancelled")))
        await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("cancelled",rid)))
        return JSONResponse(dump(ControlResponse(run_id=rid,status=RunStatus.cancelled,message=data.get("reason","cancelled"))))
    return await endpoint(request, inner)
async def inject(request):
    async def inner(r):
        req=await body(r,PipelineInjectRequest); return JSONResponse(dump(ControlResponse(run_id=req.run_id,status=RunStatus.running,message="injected")))
    return await endpoint(request, inner)
async def skip(request):
    async def inner(r):
        req=await body(r,StageSkipRequest)
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(req.run_id,));
        if not rows: raise KeyError("run")
        if req.task_id:
            tasks=await db.read("SELECT * FROM worker_tasks WHERE run_id=? AND task_id=?",(req.run_id,req.task_id))
            if not tasks: raise KeyError("task")
            task=tasks[0]
            await db.write(lambda con: con.execute("UPDATE worker_tasks SET status=?,updated_at=? WHERE run_id=? AND task_id=?",("skipped",now_utc().isoformat(),req.run_id,req.task_id)))
            await engine.emit(SSEEventType.worker_task,rows[0]["session_id"],req.run_id,WorkerTaskPayload(worker_id=task["worker_id"],task_id=req.task_id,phase_number=task["phase_number"],task_title=task["title"],status=WorkerTaskStatus.skipped))
        else:
            await db.write(lambda con: con.execute("UPDATE stage_runs SET status=? WHERE run_id=? AND stage=?",("skipped",req.run_id,req.stage.value)))
            await engine.emit(SSEEventType.stage_status,rows[0]["session_id"],req.run_id,StageStatusSchema(stage=req.stage,status=StageRunStatus.skipped,error=ErrorResponse(error_code=ErrorCode.stage_not_ready,message=req.reason)))
        await _append_handoff_skip_note(req.run_id, req.reason, req.stage, req.task_id)
        return JSONResponse(dump(ControlResponse(run_id=req.run_id,status=RunStatus.running,message="skipped")))
    return await endpoint(request, inner)

async def _append_handoff_skip_note(run_id: str, reason: str, stage: StageName, task_id: str|None):
    rows=await db.read("SELECT path,content_text FROM artifacts WHERE run_id=? AND kind='handoff' ORDER BY updated_at DESC LIMIT 1",(run_id,))
    if not rows: return
    marker="<!-- HANDOFF_NOTES_END -->"
    note=f"- Skipped {'task '+task_id if task_id else 'stage '+stage.value}: {reason}\n"
    text=rows[0]["content_text"]
    updated=text.replace(marker, note + marker, 1) if marker in text else text.rstrip()+"\n"+note
    await db.write(lambda con: con.execute("UPDATE artifacts SET content_text=?,updated_at=? WHERE run_id=? AND kind='handoff' AND path=?",(updated,now_utc().isoformat(),run_id,rows[0]["path"])))

async def assistant_reply(request):
    async def inner(r):
        req=await body(r,AssistantReplyRequest)
        model=req.model or config.providers.default_model
        provider=provider_for_model(model)
        limited=await active_rate_limit(db, provider, model)
        if limited:
            raise ProviderStartError(ErrorResponse(error_code=ErrorCode.rate_limited,message="provider rate limited",details={"provider":provider,"model":model,"reset_at":limited["reset_at"]},retryable=True))
        if not model_available(model, allow_mock=False):
            raise ProviderStartError(provider_error_for_model(model))
        prompt=("You are nexussy, a concise coding-agent control surface. "
                "Reply naturally and briefly to casual user messages. "
                "If the user asks to build, change, plan, review, or test software, tell them to describe the request or use /new; do not start work yourself.\n\n"
                f"User: {req.message}")
        result=await complete("chat", prompt, model, allow_mock=False, timeout_s=config.providers.request_timeout_s)
        return JSONResponse(dump(AssistantReplyResponse(message=result.text.strip(),model=model,usage=TokenUsage.model_validate(result.usage))))
    return await endpoint(request, inner)

async def blocker_create(request):
    async def inner(r):
        req=await body(r,BlockerCreateRequest); b=Blocker(run_id=req.run_id,worker_id=req.worker_id,stage=req.stage,severity=req.severity,message=req.message)
        await db.write(lambda con: con.execute("INSERT INTO blockers VALUES(?,?,?,?,?,?,?,?,?)",(b.blocker_id,b.run_id,b.worker_id,b.stage,b.severity,b.message,int(b.resolved),b.created_at.isoformat(),None)))
        run_rows=await db.read("SELECT status FROM runs WHERE run_id=?",(req.run_id,))
        if not run_rows: raise KeyError("run")
        if req.severity == "blocker":
            current=run_rows[0]["status"]
            if current != "blocked": engine.blocked_previous_status[req.run_id]=current
            await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",("blocked",req.run_id)))
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(req.run_id,));
        if rows: await engine.emit(SSEEventType.blocker_created,rows[0]["session_id"],req.run_id,b)
        return JSONResponse(dump(b))
    return await endpoint(request, inner)

async def blocker_resolve(request):
    async def inner(r):
        req=await body(r,BlockerResolveRequest); now=now_utc()
        rows=await db.read("SELECT * FROM blockers WHERE blocker_id=? AND run_id=?",(req.blocker_id,req.run_id));
        if not rows: raise KeyError("blocker")
        x=rows[0]; b=Blocker(blocker_id=x["blocker_id"],run_id=x["run_id"],worker_id=x["worker_id"],stage=x["stage"],severity=x["severity"],message=x["message"],resolved=True,created_at=datetime.fromisoformat(x["created_at"]),resolved_at=now)
        await db.write(lambda con: con.execute("UPDATE blockers SET resolved=1,resolved_at=? WHERE blocker_id=?",(now.isoformat(),req.blocker_id)))
        remaining=await db.read("SELECT blocker_id FROM blockers WHERE run_id=? AND severity='blocker' AND resolved=0",(req.run_id,))
        if not remaining:
            restore=engine.blocked_previous_status.pop(req.run_id, "running")
            await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?",(restore,req.run_id)))
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(req.run_id,));
        if rows: await engine.emit(SSEEventType.blocker_resolved,rows[0]["session_id"],req.run_id,b)
        return JSONResponse(dump(b))
    return await endpoint(request, inner)

async def artifacts_manifest(request):
    async def inner(r):
        sid=r.query_params["session_id"]; rid=r.query_params.get("run_id")
        if not rid:
            rows=await db.read("SELECT run_id FROM runs WHERE session_id=? ORDER BY started_at DESC LIMIT 1",(sid,)); rid=rows[0]["run_id"] if rows else None
        rows=await db.read("SELECT * FROM artifacts WHERE run_id=?",(rid,)) if rid else []
        arts=[ArtifactRef(kind=x["kind"],path=x["path"],sha256=x["sha256"],bytes=x["bytes"],updated_at=datetime.fromisoformat(x["updated_at"]),phase_number=x["phase_number"]) for x in rows]
        return JSONResponse(dump(ArtifactManifestResponse(session_id=sid,run_id=rid,artifacts=arts)))
    return await endpoint(request, inner)
async def artifact_content(request):
    async def inner(r):
        sid=r.query_params["session_id"]; kind=r.path_params["kind"]; phase=r.query_params.get("phase_number")
        rr=await db.read("SELECT run_id FROM runs WHERE session_id=? ORDER BY started_at DESC LIMIT 1",(sid,));
        if not rr: raise KeyError("run")
        rows=await db.read("SELECT * FROM artifacts WHERE run_id=? AND kind=? AND (? IS NULL OR phase_number=?) LIMIT 1",(rr[0]["run_id"],kind,phase,phase))
        if not rows: raise KeyError("artifact")
        x=rows[0]; ref=ArtifactRef(kind=x["kind"],path=x["path"],sha256=x["sha256"],bytes=x["bytes"],updated_at=datetime.fromisoformat(x["updated_at"]),phase_number=x["phase_number"])
        return JSONResponse(dump(ArtifactContentResponse(artifact=ref,content_text=x["content_text"],content_type="text/markdown" if x["path"].endswith(".md") else "application/json")))
    return await endpoint(request, inner)

async def workers(request):
    async def inner(r): return JSONResponse([dump(Worker.model_validate_json(x["worker_json"])) for x in await db.read("SELECT worker_json FROM workers WHERE run_id=?",(r.query_params["run_id"],))])
    return await endpoint(request, inner)
async def worker_get(request):
    async def inner(r):
        rows=await db.read("SELECT worker_json FROM workers WHERE run_id=? AND worker_id=?",(r.query_params["run_id"],r.path_params["worker_id"]));
        if not rows: return err(ErrorCode.worker_not_found,"worker not found",404)
        return JSONResponse(dump(Worker.model_validate_json(rows[0]["worker_json"])))
    return await endpoint(request, inner)
async def spawn(request):
    async def inner(r):
        req=await body(r,WorkerSpawnRequest); wid=f"{req.role.value}-{uuid4().hex[:8]}"; wt=str(pathlib.Path(config.projects_dir).expanduser()/"workers"/wid)
        w=Worker(worker_id=wid,run_id=req.run_id,role=req.role,status=WorkerStatus.idle,task_title=req.task,worktree_path=wt,branch_name=f"worker/{wid}",model=req.model or config.providers.default_model)
        await db.write(lambda con: con.execute("INSERT OR REPLACE INTO workers VALUES(?,?,?,?,?,?,?,?,?,?,?)",(w.worker_id,w.run_id,w.role,w.status,w.task_id,w.worktree_path,w.branch_name,w.pid,w.usage.model_dump_json(),None,w.model_dump_json())))
        rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(req.run_id,));
        if rows: await engine.emit(SSEEventType.worker_spawned,rows[0]["session_id"],req.run_id,w)
        return JSONResponse(dump(w))
    return await endpoint(request, inner)
async def assign(request):
    async def inner(r):
        req=await body(r,WorkerAssignRequest); rows=await db.read("SELECT worker_json FROM workers WHERE worker_id=? AND run_id=?",(req.worker_id,req.run_id));
        if not rows: return err(ErrorCode.worker_not_found,"worker not found",404)
        w=Worker.model_validate_json(rows[0]["worker_json"]); w.task_id=req.task_id or f"task-{uuid4().hex[:8]}"; w.task_title=req.task; w.status=WorkerStatus.assigned
        await db.write(lambda con: con.execute("UPDATE workers SET status=?, task_id=?, worker_json=? WHERE worker_id=?",(w.status,w.task_id,w.model_dump_json(),w.worker_id)))
        now=now_utc().isoformat(); await db.write(lambda con: con.execute("INSERT OR REPLACE INTO worker_tasks VALUES(?,?,?,?,?,?,?,?)",(w.task_id,w.run_id,w.worker_id,req.phase_number,req.task,WorkerTaskStatus.assigned.value,now,now)))
        run_rows=await db.read("SELECT session_id FROM runs WHERE run_id=?",(req.run_id,));
        if run_rows: await engine.emit(SSEEventType.worker_task,run_rows[0]["session_id"],req.run_id,WorkerTaskPayload(worker_id=w.worker_id,task_id=w.task_id,phase_number=req.phase_number,task_title=req.task,status=WorkerTaskStatus.assigned))
        return JSONResponse(dump(w))
    return await endpoint(request, inner)
async def worker_inject(request):
    async def inner(r): req=await body(r,WorkerInjectRequest); return JSONResponse(dump(ControlResponse(run_id=req.run_id,status=RunStatus.running,message="worker injected")))
    return await endpoint(request, inner)
async def worker_stop(request):
    async def inner(r): data=await r.json(); return JSONResponse(dump(ControlResponse(run_id=data["run_id"],status=RunStatus.running,message="worker stopped")))
    return await endpoint(request, inner)
async def file_locks(request):
    async def inner(r):
        rows=await db.read("SELECT * FROM file_locks WHERE run_id=? AND status='claimed'",(r.query_params["run_id"],)); return JSONResponse([dump(FileLock(path=x["path"],worker_id=x["worker_id"],run_id=x["run_id"],status=x["status"],claimed_at=datetime.fromisoformat(x["claimed_at"]),expires_at=datetime.fromisoformat(x["expires_at"]))) for x in rows])
    return await endpoint(request, inner)

async def get_config(request): return await endpoint(request, lambda r: asyncio.sleep(0, JSONResponse(dump(config))))
async def put_config(request):
    async def inner(r):
        global config
        next_config=NexussyConfig.model_validate(await r.json())
        cfg_path=pathlib.Path(os.environ.get("NEXUSSY_CONFIG", str(pathlib.Path(next_config.home_dir).expanduser()/"nexussy.yaml"))).expanduser()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp=cfg_path.with_suffix(cfg_path.suffix+".tmp")
        tmp.write_text(yaml.safe_dump(next_config.model_dump(mode="json"), sort_keys=False))
        tmp.replace(cfg_path)
        config=next_config
        return JSONResponse(dump(config))
    return await endpoint(request, inner)
async def secrets(request):
    async def inner(r):
        env_path=pathlib.Path(os.environ.get("NEXUSSY_ENV_FILE", str(pathlib.Path(config.home_dir).expanduser()/".env"))).expanduser()
        return JSONResponse([dump(secret_summary(n, env_path=env_path, service=config.security.keyring_service)) for n in secret_names()])
    return await endpoint(request, inner)
async def put_secret(request):
    async def inner(r):
        name=r.path_params["name"]; data=await r.json()
        if not isinstance(data, dict) or not isinstance(data.get("value"), str):
            raise ValueError([{"loc":["body","value"],"msg":"value must be a string","type":"value_error"}])
        env_path=pathlib.Path(os.environ.get("NEXUSSY_ENV_FILE", str(pathlib.Path(config.home_dir).expanduser()/".env"))).expanduser()
        return JSONResponse(dump(set_secret(name, data["value"], env_path=env_path, service=config.security.keyring_service)))
    return await endpoint(request, inner)
async def del_secret(request):
    async def inner(r):
        name=r.path_params["name"]
        env_path=pathlib.Path(os.environ.get("NEXUSSY_ENV_FILE", str(pathlib.Path(config.home_dir).expanduser()/".env"))).expanduser()
        if not delete_secret(name, env_path=env_path, service=config.security.keyring_service):
            raise KeyError(name)
        return JSONResponse(dump(ControlResponse(run_id=name,status=RunStatus.cancelled,message="secret deleted")))
    return await endpoint(request, inner)
async def memory_list(request):
    async def inner(r):
        sid=r.query_params.get("session_id"); rows=await db.read("SELECT * FROM memory_entries WHERE (? IS NULL OR session_id=?)",(sid,sid));
        return JSONResponse([dump(MemoryEntry(memory_id=x["memory_id"],session_id=x["session_id"],key=x["key"],value=x["value"],tags=json.loads(x["tags_json"]),created_at=datetime.fromisoformat(x["created_at"]),updated_at=datetime.fromisoformat(x["updated_at"]))) for x in rows])
    return await endpoint(request, inner)
async def memory_create(request):
    async def inner(r):
        req=await body(r,MemoryEntryCreateRequest); m=MemoryEntry(session_id=req.session_id,key=req.key,value=req.value,tags=req.tags)
        await db.write(lambda con: con.execute("INSERT INTO memory_entries VALUES(?,?,?,?,?,?,?)",(m.memory_id,m.session_id,m.key,m.value,json.dumps(m.tags),m.created_at.isoformat(),m.updated_at.isoformat())))
        return JSONResponse(dump(m))
    return await endpoint(request, inner)
async def memory_delete(request):
    async def inner(r): mid=r.path_params["memory_id"]; await db.write(lambda con: con.execute("DELETE FROM memory_entries WHERE memory_id=?",(mid,))); return JSONResponse(dump(ControlResponse(run_id=mid,status=RunStatus.cancelled,message="memory deleted")))
    return await endpoint(request, inner)
async def graph(request):
    async def inner(r):
        nodes=[]; edges=[]
        for s in await db.read("SELECT session_id,project_name,status FROM sessions",()): nodes.append(GraphNode(id=s["session_id"],label=s["project_name"],kind="session",status=s["status"]))
        for x in await db.read("SELECT run_id,session_id,status FROM runs",()): nodes.append(GraphNode(id=x["run_id"],label=x["run_id"],kind="run",status=x["status"])); edges.append(GraphEdge(source=x["session_id"],target=x["run_id"],kind="has_run"))
        return JSONResponse(dump(GraphResponse(nodes=nodes,edges=edges)))
    return await endpoint(request, inner)
async def events(request):
    async def inner(r): return JSONResponse([dump(e) for e in await engine.replay(r.query_params["run_id"], None, int(r.query_params.get("after_sequence",0)), int(r.query_params.get("limit",500)))])
    return await endpoint(request, inner)

routes=[Route('/health',health),Route('/assistant/reply',assistant_reply,methods=['POST']),Route('/mcp/tools',mcp_tools),Route('/mcp/call',mcp_call,methods=['POST']),Route('/sessions',sessions_create,methods=['POST']),Route('/sessions',sessions_list),Route('/sessions/{session_id}',sessions_get),Route('/sessions/{session_id}',sessions_delete,methods=['DELETE']),Route('/pipeline/start',pipeline_start,methods=['POST']),Route('/pipeline/{session_id}/interview/answer',interview_answer,methods=['POST']),Route('/pipeline/runs/{run_id}/stream',stream),Route('/pipeline/status',status),Route('/pipeline/inject',inject,methods=['POST']),Route('/pipeline/pause',control_pause,methods=['POST']),Route('/pipeline/resume',control_resume,methods=['POST']),Route('/pipeline/skip',skip,methods=['POST']),Route('/pipeline/cancel',control_cancel,methods=['POST']),Route('/pipeline/blockers',blocker_create,methods=['POST']),Route('/pipeline/blockers/resolve',blocker_resolve,methods=['POST']),Route('/pipeline/artifacts',artifacts_manifest),Route('/pipeline/artifacts/{kind}',artifact_content),Route('/swarm/workers',workers),Route('/swarm/workers/{worker_id}',worker_get),Route('/swarm/spawn',spawn,methods=['POST']),Route('/swarm/assign',assign,methods=['POST']),Route('/swarm/workers/{worker_id}/stream',stream),Route('/swarm/workers/{worker_id}/inject',worker_inject,methods=['POST']),Route('/swarm/workers/{worker_id}/stop',worker_stop,methods=['POST']),Route('/swarm/file-locks',file_locks),Route('/config',get_config),Route('/config',put_config,methods=['PUT']),Route('/secrets',secrets),Route('/secrets/{name}',put_secret,methods=['PUT']),Route('/secrets/{name}',del_secret,methods=['DELETE']),Route('/memory',memory_list),Route('/memory',memory_create,methods=['POST']),Route('/memory/{memory_id}',memory_delete,methods=['DELETE']),Route('/graph',graph),Route('/events',events)]
app=Starlette(routes=routes,on_startup=[startup])
app.add_middleware(CORSMiddleware, allow_origins=cors_origins_for(config or load_config()), allow_methods=["*"], allow_headers=["*"])

if __name__ == "__main__":
    cfg=load_config()
    uvicorn.run(app, host=cfg.core.host, port=cfg.core.port)
