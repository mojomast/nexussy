from __future__ import annotations
import pathlib

from nexussy.api.schemas import RoleCapabilityManifest, ToolName, WorkerRole
from nexussy.security import sanitize_relative_path

ORCHESTRATOR={ToolName.spawn_worker,ToolName.assign_task,ToolName.get_swarm_state,ToolName.read_file,ToolName.write_file}
ANALYST={ToolName.read_file,ToolName.list_files,ToolName.search_code,ToolName.claim_file,ToolName.release_file}
WORKER={ToolName.read_file,ToolName.write_file,ToolName.edit_file,ToolName.bash,ToolName.list_files,ToolName.search_code,ToolName.claim_file,ToolName.release_file}

_TOOL_CAPABILITY: dict[ToolName, str | None] = {
    ToolName.read_file: "read_files",
    ToolName.list_files: "read_files",
    ToolName.search_code: "read_files",
    ToolName.write_file: "write_files",
    ToolName.edit_file: "write_files",
    ToolName.bash: "run_bash",
    ToolName.spawn_worker: "spawn_subagent",
    ToolName.assign_task: "spawn_subagent",
    ToolName.get_swarm_state: None,
    ToolName.claim_file: None,
    ToolName.release_file: None,
    ToolName.add_context: None,
}

_LOCAL_TOOL_ALIASES = {
    "read": ToolName.read_file,
    "read_file": ToolName.read_file,
    "write": ToolName.write_file,
    "write_file": ToolName.write_file,
    "edit": ToolName.edit_file,
    "edit_file": ToolName.edit_file,
    "bash": ToolName.bash,
    "list": ToolName.list_files,
    "list_dir": ToolName.list_files,
    "list_files": ToolName.list_files,
    "search": ToolName.search_code,
    "search_code": ToolName.search_code,
    "spawn": ToolName.spawn_worker,
    "spawn_worker": ToolName.spawn_worker,
    "assign": ToolName.assign_task,
    "assign_task": ToolName.assign_task,
}

ROLE_CAPABILITY_MANIFESTS: dict[WorkerRole, RoleCapabilityManifest] = {
    WorkerRole.orchestrator: RoleCapabilityManifest(role=WorkerRole.orchestrator, read_files=True, write_files=True, spawn_subagent=True),
    WorkerRole.analyst: RoleCapabilityManifest(role=WorkerRole.analyst, read_files=True),
    WorkerRole.backend: RoleCapabilityManifest(role=WorkerRole.backend, read_files=True, write_files=True, run_bash=True),
    WorkerRole.frontend: RoleCapabilityManifest(role=WorkerRole.frontend, read_files=True, write_files=True, run_bash=True),
    WorkerRole.qa: RoleCapabilityManifest(role=WorkerRole.qa, read_files=True, write_files=True, run_bash=True),
    WorkerRole.devops: RoleCapabilityManifest(role=WorkerRole.devops, read_files=True, write_files=True, run_bash=True),
    WorkerRole.writer: RoleCapabilityManifest(role=WorkerRole.writer, read_files=True, write_files=True, run_bash=True),
}

def role_capability_manifest(role: WorkerRole) -> RoleCapabilityManifest:
    """Return a copy of the default capability manifest for a worker role."""
    return ROLE_CAPABILITY_MANIFESTS[role].model_copy()

def tool_name_for_runtime(tool: ToolName | str) -> ToolName:
    if isinstance(tool, ToolName):
        return tool
    try:
        return ToolName(str(tool))
    except ValueError:
        if str(tool) in _LOCAL_TOOL_ALIASES:
            return _LOCAL_TOOL_ALIASES[str(tool)]
        raise PermissionError("unknown_tool") from None

def check_tool_permission(role: WorkerRole, tool: ToolName | str, path: str | None = None) -> tuple[bool, str | None]:
    """Return whether role may use tool, without raising for expected denials."""
    try:
        normalized_tool = tool_name_for_runtime(tool)
        manifest = role_capability_manifest(role)
    except (KeyError, PermissionError):
        return False, "forbidden"
    capability = _TOOL_CAPABILITY.get(normalized_tool)
    if capability is None:
        legacy_allowed = ORCHESTRATOR if role == WorkerRole.orchestrator else ANALYST if role == WorkerRole.analyst else WORKER
        if normalized_tool not in legacy_allowed:
            return False, "forbidden"
    if capability and not bool(getattr(manifest, capability)):
        return False, "forbidden"
    if role == WorkerRole.orchestrator and normalized_tool == ToolName.write_file:
        try:
            normalized=sanitize_relative_path(path or "")
        except ValueError:
            return False, "forbidden"
        parts=pathlib.PurePosixPath(normalized).parts
        if normalized not in ("devplan.md","handoff.md") and not (parts and parts[0] == "phase"):
            return False, "forbidden"
    return True, None

def enforce_tool(role: WorkerRole, tool: ToolName, path: str | None = None) -> bool:
    allowed, reason = check_tool_permission(role, tool, path)
    if not allowed: raise PermissionError(reason or "forbidden")
    return True
