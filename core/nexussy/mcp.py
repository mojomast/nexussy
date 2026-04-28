from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from nexussy.api.schemas import PipelineStartRequest, PipelineStatusResponse, RunSummary, StageStatusSchema

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


async def call_stdio(reader, writer, *, engine=None, db=None):
    """Serve minimal newline-delimited JSON-RPC 2.0 MCP over stdio streams."""
    while True:
        line = await reader.readline()
        if not line:
            break
        request = None
        try:
            request = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
            method = request.get("method")
            params = request.get("params") or {}
            if method == "tools/list":
                result = {"tools": list_tools()}
            elif method == "tools/call":
                result = await call_tool(params["name"], params.get("arguments") or {}, engine=engine, db=db)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(mode="json")
            elif method == "initialize":
                result = {"protocolVersion":"2024-11-05","serverInfo":{"name":"nexussy","version":"1.0"},"capabilities":{"tools":{}}}
            else:
                raise KeyError(method)
            response = {"jsonrpc":"2.0","id":request.get("id"),"result":result}
        except Exception as e:
            response = {"jsonrpc":"2.0","id":request.get("id") if isinstance(request, dict) else None,"error":{"code":-32603,"message":str(e)}}
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
