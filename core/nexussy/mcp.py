from __future__ import annotations

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


async def call_stdio(*args, **kwargs):
    return {"ok": True, "degraded": True}


register("nexussy_start_pipeline", "Start a nexussy pipeline run", {"type": "object"}, _start_pipeline)
register("nexussy_get_status", "Get status for a nexussy pipeline run", {"type": "object", "required": ["run_id"]}, _get_status)
