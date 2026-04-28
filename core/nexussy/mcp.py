from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Awaitable, Callable

from nexussy.api.schemas import ArtifactManifestResponse, ArtifactRef, ControlResponse, PipelineStartRequest, PipelineStatusResponse, RunStatus, RunSummary, SessionDetail, StageStatusSchema

ToolHandler = Callable[..., Awaitable[Any]]
TOOLS: list[dict[str, Any]] = []


def register(name: str, description: str, input_schema: dict[str, Any], handler: ToolHandler) -> None:
    TOOLS.append({"name": name, "description": description, "inputSchema": input_schema, "handler": handler})


def list_tools() -> list[dict[str, Any]]:
    return [{k: v for k, v in tool.items() if k != "handler"} for tool in TOOLS]


async def call_tool(name: str, arguments: dict[str, Any] | None = None, *, engine=None, db=None) -> Any:
    for tool in TOOLS:
        if tool["name"] == name:
            return await tool["handler"](arguments or {}, engine=engine, db=db)
    raise KeyError(f"unknown tool: {name}")


async def _start_pipeline(arguments: dict[str, Any], *, engine, db=None):
    return await engine.start(PipelineStartRequest.model_validate(arguments))


async def _get_status(arguments: dict[str, Any], *, engine, db):
    run_id = arguments["run_id"]
    runs = await db.read("SELECT * FROM runs WHERE run_id=?", (run_id,))
    if not runs:
        raise KeyError("run")
    row = runs[0]
    run = RunSummary(run_id=run_id, session_id=row["session_id"], status=row["status"], current_stage=row["current_stage"], started_at=row["started_at"], finished_at=row["finished_at"])
    srows = await db.read("SELECT * FROM stage_runs WHERE run_id=? ORDER BY CASE stage WHEN 'interview' THEN 1 WHEN 'design' THEN 2 WHEN 'validate' THEN 3 WHEN 'plan' THEN 4 WHEN 'review' THEN 5 ELSE 6 END", (run_id,))
    stages = [StageStatusSchema(stage=x["stage"], status=x["status"], attempt=x["attempt"] or 0, started_at=x["started_at"], finished_at=x["finished_at"]) for x in srows]
    return PipelineStatusResponse(run=run, stages=stages, paused=bool(engine.paused.get(run_id)))


async def _pause(arguments: dict[str, Any], *, engine, db):
    run_id = arguments["run_id"]
    rows = await db.read("SELECT session_id FROM runs WHERE run_id=?", (run_id,))
    if not rows:
        raise KeyError("run")
    engine.paused[run_id] = True
    await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("paused", run_id)))
    return ControlResponse(run_id=run_id, status=RunStatus.paused, message="paused")


async def _resume(arguments: dict[str, Any], *, engine, db):
    run_id = arguments["run_id"]
    rows = await db.read("SELECT session_id FROM runs WHERE run_id=?", (run_id,))
    if not rows:
        raise KeyError("run")
    engine.paused.pop(run_id, None)
    await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("running", run_id)))
    return ControlResponse(run_id=run_id, status=RunStatus.running, message="resumed")


async def _cancel(arguments: dict[str, Any], *, engine, db):
    run_id = arguments["run_id"]
    rows = await db.read("SELECT session_id FROM runs WHERE run_id=?", (run_id,))
    if not rows:
        raise KeyError("run")
    task = engine.tasks.get(run_id)
    if task:
        task.cancel()
    engine.paused.pop(run_id, None)
    await db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("cancelled", run_id)))
    return ControlResponse(run_id=run_id, status=RunStatus.cancelled, message=arguments.get("reason", "cancelled"))


async def _get_artifacts(arguments: dict[str, Any], *, engine=None, db=None):
    run_id = arguments["run_id"]
    run_rows = await db.read("SELECT session_id FROM runs WHERE run_id=?", (run_id,))
    if not run_rows:
        raise KeyError("run")
    rows = await db.read("SELECT * FROM artifacts WHERE run_id=?", (run_id,))
    artifacts = [ArtifactRef(kind=x["kind"], path=x["path"], sha256=x["sha256"], bytes=x["bytes"], updated_at=datetime.fromisoformat(x["updated_at"]), phase_number=x["phase_number"]) for x in rows]
    return ArtifactManifestResponse(session_id=run_rows[0]["session_id"], run_id=run_id, artifacts=artifacts)


async def _list_sessions(arguments: dict[str, Any], *, engine=None, db=None):
    limit = min(int(arguments.get("limit", 50)), 200)
    offset = int(arguments.get("offset", 0))
    rows = await db.read("SELECT detail_json FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [SessionDetail.model_validate_json(row["detail_json"]).session.model_dump(mode="json") for row in rows]


def _json_rpc_error(code: int, message: str, request_id=None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def call_stdio(reader, writer, *, engine=None, db=None):
    """Serve minimal newline-delimited JSON-RPC 2.0 MCP over stdio streams."""
    while True:
        line = await reader.readline()
        if not line:
            break
        request = None
        try:
            request = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
        except json.JSONDecodeError as e:
            response = _json_rpc_error(-32700, str(e), None)
        else:
            response = None
            request_id = request.get("id") if isinstance(request, dict) else None
            is_notification = isinstance(request, dict) and "id" not in request
            method = request.get("method") if isinstance(request, dict) else None
            params = request.get("params") or {} if isinstance(request, dict) else {}
            if not isinstance(request, dict) or not isinstance(method, str):
                response = _json_rpc_error(-32600, "missing or invalid method", request_id)
            elif method == "notifications/initialized":
                if not is_notification:
                    response = {"jsonrpc":"2.0","id":request_id,"result":{}}
            else:
                try:
                    if method == "tools/list":
                        result = {"tools": list_tools()}
                    elif method == "tools/call":
                        result = await call_tool(params["name"], params.get("arguments") or {}, engine=engine, db=db)
                        if hasattr(result, "model_dump"):
                            result = result.model_dump(mode="json")
                    elif method == "initialize":
                        result = {"protocolVersion":"2024-11-05","serverInfo":{"name":"nexussy","version":"1.0"},"capabilities":{"tools":{}}}
                    else:
                        response = _json_rpc_error(-32601, f"unknown method: {method}", request_id)
                        result = None
                    if response is None and not is_notification:
                        response = {"jsonrpc":"2.0","id":request_id,"result":result}
                except Exception as e:
                    if not is_notification:
                        response = _json_rpc_error(-32603, str(e), request_id)
        if response is not None:
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            drain = getattr(writer, "drain", None)
            if drain:
                await drain()
    close = getattr(writer, "close", None)
    if close:
        close()


register(
    "nexussy_start_pipeline",
    "Start a nexussy pipeline run",
    {
        "type": "object",
        "required": ["project_name", "description"],
        "properties": {
            "project_name": {"type": "string", "description": "Name of the project"},
            "description": {"type": "string", "description": "What to build"},
            "project_slug": {"type": "string"},
            "auto_approve_interview": {"type": "boolean"},
            "existing_repo_path": {"type": "string"},
            "start_stage": {"type": "string", "enum": ["interview", "design", "validate", "plan", "review", "develop"]},
            "stop_after_stage": {"type": "string", "enum": ["interview", "design", "validate", "plan", "review", "develop"]},
            "resume_run_id": {"type": "string"},
            "model_overrides": {"type": "object"},
            "metadata": {"type": "object"},
        },
    },
    _start_pipeline,
)
register("nexussy_get_status", "Get status for a nexussy pipeline run", {"type": "object", "required": ["run_id"]}, _get_status)
register("nexussy_pause", "Pause a nexussy pipeline run", {"type": "object", "required": ["run_id"]}, _pause)
register("nexussy_resume", "Resume a nexussy pipeline run", {"type": "object", "required": ["run_id"]}, _resume)
register("nexussy_cancel", "Cancel a nexussy pipeline run", {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}, "reason": {"type": "string"}}}, _cancel)
register("nexussy_get_artifacts", "Get artifact manifest for a run", {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}}}, _get_artifacts)
register("nexussy_list_sessions", "List recent nexussy sessions", {"type": "object", "properties": {"limit": {"type": "integer"}, "offset": {"type": "integer"}}}, _list_sessions)
