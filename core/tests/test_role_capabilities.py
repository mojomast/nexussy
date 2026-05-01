import pytest
from pydantic import ValidationError

from nexussy.api.schemas import RoleCapabilityManifest, ToolName, WorkerRole
from nexussy.swarm.roles import ROLE_CAPABILITY_MANIFESTS, check_tool_permission, enforce_tool, role_capability_manifest


def test_every_worker_role_has_capability_manifest():
    assert set(ROLE_CAPABILITY_MANIFESTS) == set(WorkerRole)
    for role, manifest in ROLE_CAPABILITY_MANIFESTS.items():
        assert manifest.role == role
        assert isinstance(manifest, RoleCapabilityManifest)


def test_role_capability_defaults_are_strict_and_safe():
    spawn_roles = [role for role, manifest in ROLE_CAPABILITY_MANIFESTS.items() if manifest.spawn_subagent]
    assert spawn_roles == [WorkerRole.orchestrator]

    analyst = ROLE_CAPABILITY_MANIFESTS[WorkerRole.analyst]
    assert analyst.read_files is True
    assert analyst.write_files is False
    assert analyst.run_bash is False
    assert analyst.spawn_subagent is False

    with pytest.raises(ValidationError):
        RoleCapabilityManifest(role=WorkerRole.backend, read_files=True, unknown=True)


def test_role_manifest_copy_does_not_mutate_defaults():
    manifest = role_capability_manifest(WorkerRole.backend)
    manifest.write_files = False
    assert ROLE_CAPABILITY_MANIFESTS[WorkerRole.backend].write_files is True


def test_existing_toolname_enforcement_compatibility_remains():
    assert enforce_tool(WorkerRole.backend, ToolName.bash)
    assert enforce_tool(WorkerRole.analyst, ToolName.read_file)
    with pytest.raises(PermissionError):
        enforce_tool(WorkerRole.analyst, ToolName.write_file)
    assert enforce_tool(WorkerRole.orchestrator, ToolName.write_file, "devplan.md")


def test_manifest_backed_runtime_permission_mapping():
    assert check_tool_permission(WorkerRole.analyst, ToolName.read_file)[0] is True
    assert check_tool_permission(WorkerRole.analyst, "list_dir")[0] is True
    assert check_tool_permission(WorkerRole.analyst, ToolName.search_code)[0] is True
    assert check_tool_permission(WorkerRole.analyst, ToolName.write_file)[0] is False
    assert check_tool_permission(WorkerRole.analyst, ToolName.edit_file)[0] is False
    assert check_tool_permission(WorkerRole.analyst, ToolName.bash)[0] is False
    assert check_tool_permission(WorkerRole.backend, ToolName.bash)[0] is True
    assert check_tool_permission(WorkerRole.backend, ToolName.spawn_worker)[0] is False
    assert check_tool_permission(WorkerRole.backend, ToolName.assign_task)[0] is False
    assert check_tool_permission(WorkerRole.backend, ToolName.get_swarm_state)[0] is False
    assert check_tool_permission(WorkerRole.orchestrator, ToolName.spawn_worker)[0] is True


def test_orchestrator_plan_artifact_write_restriction_still_applies():
    assert check_tool_permission(WorkerRole.orchestrator, ToolName.write_file, "devplan.md")[0] is True
    assert check_tool_permission(WorkerRole.orchestrator, ToolName.write_file, "phase/01/notes.md")[0] is True
    assert check_tool_permission(WorkerRole.orchestrator, ToolName.write_file, "src/app.py")[0] is False
