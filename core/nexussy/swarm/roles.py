from __future__ import annotations
import pathlib

from nexussy.api.schemas import RoleCapabilityManifest, ToolName, WorkerRole
from nexussy.security import sanitize_relative_path

ORCHESTRATOR={ToolName.spawn_worker,ToolName.assign_task,ToolName.get_swarm_state,ToolName.read_file,ToolName.write_file}
ANALYST={ToolName.read_file,ToolName.list_files,ToolName.search_code,ToolName.claim_file,ToolName.release_file}
WORKER={ToolName.read_file,ToolName.write_file,ToolName.edit_file,ToolName.bash,ToolName.list_files,ToolName.search_code,ToolName.claim_file,ToolName.release_file}

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
