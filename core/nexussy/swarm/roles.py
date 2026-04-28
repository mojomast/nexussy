from __future__ import annotations
import pathlib

from nexussy.api.schemas import WorkerRole, ToolName
from nexussy.security import sanitize_relative_path

ORCHESTRATOR={ToolName.spawn_worker,ToolName.assign_task,ToolName.get_swarm_state,ToolName.read_file,ToolName.write_file}
ANALYST={ToolName.read_file,ToolName.list_files,ToolName.search_code,ToolName.claim_file,ToolName.release_file}
WORKER={ToolName.read_file,ToolName.write_file,ToolName.edit_file,ToolName.bash,ToolName.list_files,ToolName.search_code,ToolName.claim_file,ToolName.release_file}

def enforce_tool(role: WorkerRole, tool: ToolName, path: str | None = None) -> bool:
    allowed = ORCHESTRATOR if role == WorkerRole.orchestrator else ANALYST if role == WorkerRole.analyst else WORKER
    if tool not in allowed: raise PermissionError("forbidden")
    if role == WorkerRole.orchestrator and tool == ToolName.write_file:
        try:
            normalized=sanitize_relative_path(path or "")
        except ValueError as exc:
            raise PermissionError("forbidden") from exc
        parts=pathlib.PurePosixPath(normalized).parts
        if normalized not in ("devplan.md","handoff.md") and not (parts and parts[0] == "phase"):
            raise PermissionError("forbidden")
    return True
