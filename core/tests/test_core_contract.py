import asyncio, json, os, sqlite3, sys, threading, types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from nexussy.api.schemas import ErrorCode, ErrorResponse, PipelineStartRequest, EventEnvelope, RunSummary, RunStatus, SSEEventType, ArtifactRef, StageName, Worker, WorkerStatus, WorkerTaskStatus
from nexussy.api import server
from nexussy.api.server import app
from nexussy.artifacts.store import safe_write
from nexussy.config import load_config
from nexussy.db import CURRENT_SCHEMA_VERSION, Database
from nexussy.security import sanitize_path, sanitize_relative_path, scrub_log
from nexussy.swarm.locks import claim_file
from nexussy.swarm.roles import enforce_tool
from nexussy.api.schemas import WorkerRole, ToolName
from nexussy.providers import active_rate_limit, complete, persist_rate_limit, select_stage_model
from nexussy.providers import DISCOVERY, delete_secret, secret_summary, set_secret
from nexussy.providers import ProviderResult
from nexussy.swarm.gitops import _git, init_repo, create_worktree, commit_worker, merge_no_ff, extract_changed_files, prune_worktrees
from nexussy.swarm.locks import write_requires_lock
from nexussy.swarm.pi_rpc import PiRPCProcess, spawn_pi_worker
from nexussy.pipeline.engine import Engine, complexity
from nexussy.pipeline.engine import STAGES
from nexussy.checkpoint import STAGE_ORDER, save_checkpoint


def test_schema_forbids_extra():
    with pytest.raises(Exception):
        ErrorResponse(error_code="bad_request", message="x", extra=1)
    with pytest.raises(Exception):
        PipelineStartRequest(project_name="Bad", description="x", project_slug="Bad Slug")
    with pytest.raises(Exception):
        PipelineStartRequest(project_name="Bad", description="x", model_overrides={"design":"badmodel"})
    with pytest.raises(Exception):
        PipelineStartRequest(project_name="Bad", description="x", metadata={"bad": object()})
    with pytest.raises(Exception):
        ArtifactRef(kind="devplan", path="devplan.md", sha256="a", updated_at=datetime.now())


def test_security_helpers(tmp_path):
    assert sanitize_relative_path("a/b.txt") == "a/b.txt"
    with pytest.raises(ValueError):
        sanitize_relative_path("")
    with pytest.raises(ValueError):
        sanitize_relative_path("/")
    with pytest.raises(ValueError):
        sanitize_relative_path("../x")
    with pytest.raises(ValueError):
        sanitize_relative_path("\x00foo")
    assert sanitize_relative_path("foo/bar") == "foo/bar"
    assert "[REDACTED]" in scrub_log("Authorization: Bearer abc.def.ghi password=secret")
    assert "[REDACTED]" in scrub_log("Bearer provider-token-123")
    assert "[REDACTED]" in scrub_log("token=" + "a" * 40)
    assert "[REDACTED]" in scrub_log("secret=" + "b" * 64)
    assert "[REDACTED]" in scrub_log("OPENAI_API_KEY=sk-secretsecretsecret")
    assert "[REDACTED]" in scrub_log("ANTHROPIC_API_KEY=anthropic-secret-value")
    assert "[REDACTED]" in scrub_log("ghp_" + "A" * 36)
    assert "[REDACTED]" in scrub_log("ghs_" + "Z" * 36)
    private_key = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
    assert "[REDACTED]" in scrub_log(private_key)
    git_sha = "a" * 40
    short_hash = "a" * 39
    sha256 = "c" * 64
    upper_hex = "D" * 40
    assert short_hash in scrub_log("token=" + short_hash)
    assert git_sha in scrub_log("commit " + git_sha)
    assert "commit_hash=" + git_sha in scrub_log("commit_hash=" + git_sha)
    assert "sha=" + git_sha in scrub_log("sha=" + git_sha)
    assert "base_commit=" + git_sha in scrub_log("base_commit=" + git_sha)
    assert "hash_value=" + sha256 in scrub_log("hash_value=" + sha256)
    assert "[REDACTED]" in scrub_log("api_key=" + git_sha)
    assert upper_hex in scrub_log("token=" + upper_hex)
    root = tmp_path / "root"; root.mkdir(); outside = tmp_path / "outside"; outside.mkdir()
    with pytest.raises(ValueError): sanitize_path(str(outside / "x"), [str(root)])
    link = root / "link"; link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError): sanitize_path(str(link / "x"), [str(root)])


def test_config_precedence(tmp_path, monkeypatch):
    cfg = tmp_path / "nexussy.yaml"; env = tmp_path / ".env"
    cfg.write_text("core:\n  port: 1111\n")
    env.write_text("NEXUSSY_CORE_PORT=2222\n")
    monkeypatch.setenv("NEXUSSY_CONFIG", str(cfg)); monkeypatch.setenv("NEXUSSY_ENV_FILE", str(env)); monkeypatch.setenv("NEXUSSY_CORE_PORT", "3333")
    assert load_config().core.port == 3333


def test_provider_model_precedence_and_worker_override(monkeypatch):
    monkeypatch.setenv("NEXUSSY_DESIGN_MODEL", "anthropic/claude-test")
    cfg = load_config({"providers":{"default_model":"openai/default"}})
    assert select_stage_model(cfg, "design") == "anthropic/claude-test"
    assert select_stage_model(cfg, "design", {"design":"openrouter/request"}) == "openrouter/request"


def test_glm_key_is_zai_provider_alias():
    assert DISCOVERY["GLM_API_KEY"] == "zai"
    assert DISCOVERY["ZAI_API_KEY"] == "zai"


def test_complexity_uses_word_boundary_signals():
    assert "multiple_languages" in complexity("deploy a go backend").signals
    assert "deployment" in complexity("deploy a go backend").signals
    assert "auth" in complexity("add authentication").signals
    assert "persistence" in complexity("postgres db").signals
    assert "auth" not in complexity("cargo package manager").signals


def test_engine_stages_follow_checkpoint_stage_order():
    assert [stage.value for stage in STAGES] == STAGE_ORDER


@pytest.mark.asyncio
async def test_checkpoint_hash_uses_content_when_provided(tmp_path):
    db = Database(str(tmp_path / "state.db"))
    await db.init()
    first = await save_checkpoint(db, "run-1", StageName.design, ".nexussy/checkpoints/design-a.json", content="first content")
    second = await save_checkpoint(db, "run-1", StageName.design, ".nexussy/checkpoints/design-b.json", content="second content")
    assert first.sha256 != second.sha256


def test_safe_write_anchor_validation(tmp_path):
    content = "# DevPlan\n<!-- PROGRESS_LOG_START -->\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n<!-- NEXT_TASK_GROUP_END -->\n"
    meta = safe_write(str(tmp_path), "devplan.md", content)
    assert meta["bytes"] > 0
    with pytest.raises(ValueError):
        safe_write(str(tmp_path), "handoff.md", "bad")


def test_api_pipeline_and_replay(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    with TestClient(app) as c:
        h = c.get("/health").json()
        assert h["ok"] and h["contract_version"] == "1.0" and h["db_ok"]
        r = c.post("/pipeline/start", json={"project_name":"Demo","description":"small python api with tests","auto_approve_interview":True,"metadata":{"mock_provider":True}}).json()
        assert r["status"] == "running"
        # Wait until deterministic background run finishes and events are persisted.
        for _ in range(50):
            ev = c.get("/events", params={"run_id": r["run_id"]}).json()
            if ev and ev[-1]["type"] == "done": break
            import time; time.sleep(.05)
        types = [e["type"] for e in ev]
        assert "run_started" in types and types.count("stage_transition") == 6 and "checkpoint_saved" in types and types[-1] == "done"
        missed = c.get("/events", params={"run_id": r["run_id"], "after_sequence": ev[0]["sequence"]}).json()
        assert missed[0]["sequence"] == ev[1]["sequence"]
        assert c.get("/pipeline/status", params={"run_id": r["run_id"]}).json()["ok"]


def test_resume_run_id_skips_checkpointed_stages(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        first = c.post("/pipeline/start", json={"project_name":"Resume Demo","description":"small api","auto_approve_interview":True,"stop_after_stage":"design","metadata":{"mock_provider":True}}).json()
        for _ in range(100):
            ev = c.get("/events", params={"run_id": first["run_id"]}).json()
            if ev and ev[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev[-1]["payload"]["final_status"] == "passed"
        last_sequence = ev[-1]["sequence"]

        second = c.post("/pipeline/start", json={"project_name":"Resume Demo","description":"small api","auto_approve_interview":True,"resume_run_id":first["run_id"],"stop_after_stage":"validate","metadata":{"mock_provider":True}})
        assert second.status_code == 200, second.text
        assert c.get("/pipeline/status", params={"run_id": first["run_id"]}).json()["run"]["current_stage"] == "validate"
        for _ in range(100):
            resumed_events = c.get("/events", params={"run_id": first["run_id"], "after_sequence": last_sequence}).json()
            if resumed_events and resumed_events[-1]["type"] == "done": break
            import time; time.sleep(.05)
        transitions = [e for e in resumed_events if e["type"] == "stage_transition"]
        assert transitions and transitions[0]["payload"]["to_stage"] == "validate"
        assert all(e["payload"]["to_stage"] not in ("interview", "design") for e in transitions)


def test_mcp_tools_and_start_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        tools = c.get("/mcp/tools")
        assert tools.status_code == 200, tools.text
        names = {tool["name"] for tool in tools.json()["tools"]}
        assert {"nexussy_start_pipeline", "nexussy_get_status", "nexussy_list_sessions", "nexussy_get_artifacts", "nexussy_interview_answer", "nexussy_pause", "nexussy_resume", "nexussy_cancel", "nexussy_inject", "nexussy_worker_spawn", "nexussy_worker_assign", "nexussy_list_workers"} <= names
        assert all("inputSchema" in tool for tool in tools.json()["tools"])
        started = c.post("/mcp/call", json={"name":"nexussy_start_pipeline","arguments":{"project_name":"MCP Demo","description":"small api","auto_approve_interview":True,"metadata":{"mock_provider":True}}})
        assert started.status_code == 200, started.text
        assert started.json()["run_id"]
        spawned = c.post("/mcp/call", json={"name":"nexussy_worker_spawn","arguments":{"run_id":started.json()["run_id"],"role":"backend","task":"implement api"}})
        assert spawned.status_code == 200, spawned.text
        assert spawned.json()["status"] == "idle"
        listed = c.post("/mcp/call", json={"name":"nexussy_list_workers","arguments":{"run_id":started.json()["run_id"]}})
        assert listed.status_code == 200, listed.text
        assert spawned.json()["worker_id"] in {worker["worker_id"] for worker in listed.json()}


def test_route_validation_error_is_normalized(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Bad","description":"x","unexpected":True})
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and body["error_code"] == "validation_error"
        assert body["details"]["errors"]


def test_delete_session_with_delete_files_removes_project_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    with TestClient(app) as c:
        created = c.post("/sessions", json={"project_name":"Delete Me","description":"x"})
        assert created.status_code == 200, created.text
        detail = created.json()
        project_root = Path(detail["project_root"])
        (project_root / "main" / "keep.txt").write_text("remove me")
        deleted = c.delete(f"/sessions/{detail['session']['session_id']}", params={"delete_files":"true"})
        assert deleted.status_code == 200, deleted.text
        assert not project_root.exists()


def test_pipeline_cancel_unknown_run_returns_404(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    with TestClient(app) as c:
        r = c.post("/pipeline/cancel", json={"run_id":"missing-run"})
        assert r.status_code == 404
        assert r.json()["details"]["key"] == "'run'"


def test_config_put_persists_yaml(monkeypatch, tmp_path):
    cfg_path = tmp_path / "nexussy.yaml"
    monkeypatch.setenv("NEXUSSY_CONFIG", str(cfg_path))
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        cfg = c.get("/config").json()
        cfg["providers"]["default_model"] = "openrouter/openai/gpt-4o-mini"
        r = c.put("/config", json=cfg)
        assert r.status_code == 200, r.text
        assert "openrouter/openai/gpt-4o-mini" in cfg_path.read_text()
        assert load_config().providers.default_model == "openrouter/openai/gpt-4o-mini"


def test_config_put_rejects_auth_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_CONFIG", str(tmp_path / "nexussy.yaml"))
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config({"auth":{"enabled":True}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.put("/config", json={"auth":{"enabled":False}})
        assert r.status_code == 403
        body = r.json()
        assert body["ok"] is False and body["error_code"] == "forbidden"
        assert "auth.enabled" in body["details"]["forbidden_keys"]


def test_validate_review_correction_loops_and_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Loops","description":"small api","auto_approve_interview":True,"stop_after_stage":"review","metadata":{"validate_fail_iterations":1}})
        assert r.status_code == 200, r.text
        body = r.json()
        for _ in range(100):
            ev = c.get("/events", params={"run_id": body["run_id"]}).json()
            if ev and ev[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev[-1]["payload"]["final_status"] == "passed"
        assert any(e["type"] == "stage_transition" and e["payload"]["reason"] == "validation corrections returned to design" for e in ev)
        assert c.post("/pipeline/pause", json={"run_id":body["run_id"],"reason":"check"}).json()["status"] == "paused"
        blocker = c.post("/pipeline/blockers", json={"run_id":body["run_id"],"stage":"develop","message":"waiting"}).json()
        assert c.get("/pipeline/status", params={"run_id":body["run_id"]}).json()["blockers"][0]["blocker_id"] == blocker["blocker_id"]
        assert c.post("/pipeline/blockers/resolve", json={"run_id":body["run_id"],"blocker_id":blocker["blocker_id"]}).json()["resolved"] is True
        types = [e["type"] for e in c.get("/events", params={"run_id": body["run_id"]}).json()]
        assert "pause_state_changed" in types and "blocker_created" in types and "blocker_resolved" in types


def test_validate_and_review_max_iteration_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"ValidateFail","description":"small api","auto_approve_interview":True,"stop_after_stage":"validate","metadata":{"force_validate_fail":True}}).json()
        for _ in range(100):
            ev = c.get("/events", params={"run_id": r["run_id"]}).json()
            if ev and ev[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev[-1]["payload"]["final_status"] == "failed"
        assert any("validate max iterations" in json.dumps(e) for e in ev)
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "design" for e in ev)
        r2 = c.post("/pipeline/start", json={"project_name":"ReviewFail","description":"small api with tests","auto_approve_interview":True,"stop_after_stage":"review","metadata":{"force_review_fail":True}}).json()
        for _ in range(100):
            ev2 = c.get("/events", params={"run_id": r2["run_id"]}).json()
            if ev2 and ev2[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev2[-1]["payload"]["final_status"] == "failed"
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "plan" for e in ev2)


def _wait_done(client, run_id):
    for _ in range(300):
        ev = client.get("/events", params={"run_id": run_id}).json()
        if ev and ev[-1]["type"] == "done":
            return ev
        import time; time.sleep(.05)
    return ev


def test_validate_clean_emits_passed_validation_report(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    async def fake_provider(self, st, sid, rid, prompt, selected_models, allow_mock):
        if st == StageName.design:
            return "# Goals\nBuild it.\n# Architecture\nSimple.\n# Dependencies\nPython.\n# Risks\nLow.\n# Test Strategy\nPytest.\n"
        if st == StageName.validate:
            return '{"passed": true, "issues": []}'
        return "[]"
    monkeypatch.setattr(Engine, "_provider_text", fake_provider)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Validate Clean","description":"small api","auto_approve_interview":True,"stop_after_stage":"validate","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        report = json.loads(c.get("/pipeline/artifacts/validation_report", params={"session_id":r["session_id"]}).json()["content_text"])
        assert report["passed"] is True and report["issues"] == []


def test_review_clean_emits_passed_review_report(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    async def fake_provider(self, st, sid, rid, prompt, selected_models, allow_mock):
        if st == StageName.plan:
            return "# DevPlan\n<!-- PROGRESS_LOG_START -->\n- ready\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: build.\n<!-- NEXT_TASK_GROUP_END -->\n"
        if st == StageName.review:
            return '{"passed": true, "issues": [], "feedback_for_plan_stage": ""}'
        if st == StageName.design:
            return "# Goals\nBuild it.\n# Architecture\nSimple.\n# Dependencies\nPython.\n# Risks\nLow.\n# Test Strategy\nPytest.\n"
        if st == StageName.validate:
            return '{"passed": true, "issues": []}'
        return "[]"
    monkeypatch.setattr(Engine, "_provider_text", fake_provider)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Review Clean","description":"small api","auto_approve_interview":True,"stop_after_stage":"review","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        report = json.loads(c.get("/pipeline/artifacts/review_report", params={"session_id":r["session_id"]}).json()["content_text"])
        assert report["passed"] is True and report["issues"] == []


def test_validate_provider_issues_retry_to_design(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    calls = {"validate": 0}
    async def fake_provider(self, st, sid, rid, prompt, selected_models, allow_mock):
        if st == StageName.design:
            return "# Goals\nBuild it.\n# Architecture\nSimple.\n# Dependencies\nPython.\n# Risks\nLow.\n# Test Strategy\nPytest.\n"
        if st == StageName.validate:
            calls["validate"] += 1
            if calls["validate"] == 1:
                return '{"passed": false, "issues": [{"severity":"error", "category":"design", "message":"missing dependency", "fix_required": true}]}'
            return '{"passed": true, "issues": []}'
        return "[]"
    monkeypatch.setattr(Engine, "_provider_text", fake_provider)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Validate Issue","description":"small api","auto_approve_interview":True,"stop_after_stage":"validate","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        assert calls["validate"] == 2
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "design" for e in ev)


def test_provider_passed_false_empty_issues_retry_validate_and_review(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    calls = {"validate": 0, "review": 0}
    async def fake_provider(self, st, sid, rid, prompt, selected_models, allow_mock):
        if st == StageName.design:
            return "# Goals\nBuild it.\n# Architecture\nSimple.\n# Dependencies\nPython.\n# Risks\nLow.\n# Test Strategy\nPytest.\n"
        if st == StageName.validate:
            calls["validate"] += 1
            return '{"passed": false, "issues": []}' if calls["validate"] == 1 else '{"passed": true, "issues": []}'
        if st == StageName.plan:
            return "# DevPlan\n<!-- PROGRESS_LOG_START -->\n- ready\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: build.\n<!-- NEXT_TASK_GROUP_END -->\n"
        if st == StageName.review:
            calls["review"] += 1
            return '{"passed": false, "issues": [], "feedback_for_plan_stage": "Add acceptance criteria"}' if calls["review"] == 1 else '{"passed": true, "issues": []}'
        return "[]"
    monkeypatch.setattr(Engine, "_provider_text", fake_provider)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Explicit False","description":"small api","auto_approve_interview":True,"stop_after_stage":"review","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        assert calls == {"validate": 2, "review": 2}
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "design" for e in ev)
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "plan" for e in ev)


def test_review_feedback_is_injected_into_replan_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    prompts = []
    calls = {"review": 0}
    async def fake_provider(self, st, sid, rid, prompt, selected_models, allow_mock):
        if st == StageName.plan:
            prompts.append(prompt)
            return "# DevPlan\n<!-- PROGRESS_LOG_START -->\n- ready\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: build.\n<!-- NEXT_TASK_GROUP_END -->\n"
        if st == StageName.review:
            calls["review"] += 1
            return '{"passed": false, "issues": [], "feedback_for_plan_stage": "Add owner, acceptance, and tests"}' if calls["review"] == 1 else '{"passed": true, "issues": []}'
        if st == StageName.design:
            return "# Goals\nBuild it.\n# Architecture\nSimple.\n# Dependencies\nPython.\n# Risks\nLow.\n# Test Strategy\nPytest.\n"
        if st == StageName.validate:
            return '{"passed": true, "issues": []}'
        return "[]"
    monkeypatch.setattr(Engine, "_provider_text", fake_provider)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Feedback","description":"small api","auto_approve_interview":True,"stop_after_stage":"review","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
    assert len(prompts) == 2
    assert "Add owner, acceptance, and tests" in prompts[1]


@pytest.mark.asyncio
async def test_provider_text_retries_per_stage_config(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "state.db")); await db.init()
    cfg = load_config({"stages":{"design":{"max_retries":2}}, "providers":{"retry_base_ms":1}})
    engine = Engine(db, cfg)
    await db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",("rid","sid","running","design",datetime.now(timezone.utc).isoformat(),None,"{}")))
    calls = {"n": 0}
    async def flaky_complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("temporary provider failure")
        return ProviderResult("ok", {"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model})
    monkeypatch.setattr("nexussy.pipeline.engine.complete", flaky_complete)
    assert await engine._provider_text(StageName.design, "sid", "rid", "prompt", {}, True) == "ok"
    assert calls["n"] == 2


def test_plan_devplan_content_matches_mock_provider_output(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    expected = "# DevPlan\n<!-- PROGRESS_LOG_START -->\n- provider plan\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: provider task.\n<!-- NEXT_TASK_GROUP_END -->\n"
    async def fake_provider(self, st, sid, rid, prompt, selected_models, allow_mock):
        if st == StageName.plan:
            return f"```markdown\n{expected}```"
        if st == StageName.design:
            return "# Goals\nBuild it.\n# Architecture\nSimple.\n# Dependencies\nPython.\n# Risks\nLow.\n# Test Strategy\nPytest.\n"
        if st == StageName.validate:
            return '{"passed": true, "issues": []}'
        return "[]"
    monkeypatch.setattr(Engine, "_provider_text", fake_provider)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Provider Plan","description":"small api","auto_approve_interview":True,"stop_after_stage":"plan","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        content = c.get("/pipeline/artifacts/devplan", params={"session_id":r["session_id"]}).json()["content_text"]
        assert content == expected


def test_provider_mock_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False); monkeypatch.delenv("NEXUSSY_MOCK_PROVIDER", raising=False)
    empty_env = tmp_path / ".env"; empty_env.write_text("")
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(empty_env))
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"No Provider","description":"x"})
        assert r.status_code == 503
        assert r.json()["error_code"] in ("model_unavailable", "provider_unavailable")
        ok = c.post("/pipeline/start", json={"project_name":"Mock Provider","description":"x","metadata":{"mock_provider":True}})
        assert ok.status_code == 200


def test_assistant_reply_uses_configured_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    monkeypatch.setenv("NEXUSSY_DEFAULT_MODEL", "openrouter/openai/gpt-4o-mini")
    server.config = load_config({"providers":{"default_model":"openrouter/openai/gpt-4o-mini"}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/assistant/reply", json={"message":"hi"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["model"] == "openrouter/openai/gpt-4o-mini"
        assert "fake provider chat output" in body["message"]


def test_assistant_reply_requires_real_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUSSY_PROVIDER_MODE", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    empty_env = tmp_path / ".env"; empty_env.write_text("")
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(empty_env))
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config({"providers":{"default_model":"openrouter/openai/gpt-4o-mini"}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/assistant/reply", json={"message":"hi"})
        assert r.status_code == 503
        assert r.json()["error_code"] == "model_unavailable"


def test_assistant_reply_rate_limit_sets_retry_after(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_DEFAULT_MODEL", "openrouter/openai/gpt-4o-mini")
    server.config = load_config({"providers":{"default_model":"openrouter/openai/gpt-4o-mini"}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    reset_at = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    asyncio.run(server.db.init())
    asyncio.run(persist_rate_limit(server.db, "openrouter", "openrouter/openai/gpt-4o-mini", reset_at, "quota"))
    with TestClient(app) as c:
        r = c.post("/assistant/reply", json={"message":"hi"})
        assert r.status_code == 429
        assert r.json()["error_code"] == ErrorCode.rate_limited.value
        assert r.headers["Retry-After"] == str(int(reset_at.timestamp()))


def test_health_reports_pi_availability(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PI_COMMAND", "/no/such/pi-nexussy-test")
    server.config = load_config({"pi":{"command":"/no/such/pi-nexussy-test","args":[]}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        assert c.get("/health").json()["pi_available"] is False
    monkeypatch.setenv("NEXUSSY_PI_COMMAND", "pi")
    server.config = load_config({"pi":{"command":"pi","args":[]}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        assert c.get("/health").json()["pi_available"] is True


def test_cors_uses_runtime_config_not_import_time_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config({"core":{"cors_allow_origins":["https://runtime.example"]}, "security":{"cors_origins":["https://ignored.example"]}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    server.app.middleware_stack = None
    with TestClient(app) as c:
        allowed = c.get("/health", headers={"Origin":"https://runtime.example"})
        denied = c.get("/health", headers={"Origin":"https://import.example"})
    assert allowed.headers.get("access-control-allow-origin") == "https://runtime.example"
    assert "access-control-allow-origin" not in denied.headers
    monkeypatch.setenv("NEXUSSY_CORS_ALLOW_ORIGINS", "https://env-one.example, https://env-two.example")
    assert load_config().core.cors_allow_origins == ["https://env-one.example", "https://env-two.example"]


def test_provider_keys_load_from_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-file-secret\n")
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(env))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert "openai" in server.configured_providers()


def test_secrets_api_uses_keyring_without_echo(monkeypatch, tmp_path):
    store = {}
    fake_keyring = types.SimpleNamespace(
        get_password=lambda service, name: store.get((service, name)),
        set_password=lambda service, name, value: store.__setitem__((service, name), value),
        delete_password=lambda service, name: store.pop((service, name)),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        secret = "sk-test-secret-value"
        r = c.put("/secrets/OPENAI_API_KEY", json={"value": secret})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "OPENAI_API_KEY" and body["source"] == "keyring" and body["configured"] is True
        assert os.environ.get("OPENAI_API_KEY") is None
        assert secret_summary("OPENAI_API_KEY").source == "keyring"
        assert secret not in r.text
        listed = c.get("/secrets").json()
        assert any(x["name"] == "OPENAI_API_KEY" and x["source"] == "keyring" and x["configured"] for x in listed)
        assert secret not in json.dumps(listed)
        assert c.delete("/secrets/OPENAI_API_KEY").status_code == 200
        assert c.delete("/secrets/OPENAI_API_KEY").status_code == 404


def test_delete_secret_reports_keyring_only_secret_existed(monkeypatch, tmp_path):
    store = {("nexussy", "OPENAI_API_KEY"): "sk-keyring-only"}
    fake_keyring = types.SimpleNamespace(
        get_password=lambda service, name: store.get((service, name)),
        delete_password=lambda service, name: store.pop((service, name)),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"; env.write_text("")
    assert delete_secret("OPENAI_API_KEY", env_path=env, service="nexussy") is True
    assert store == {}


def test_secrets_api_falls_back_to_env_file_and_validates(monkeypatch, tmp_path, caplog):
    class BrokenKeyring:
        def get_password(self, service, name): raise RuntimeError("no keyring")
        def set_password(self, service, name, value): raise RuntimeError("no keyring")
        def delete_password(self, service, name): raise RuntimeError("no keyring")
    monkeypatch.setitem(sys.modules, "keyring", BrokenKeyring())
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        assert c.put("/secrets/BAD_KEY", json={"value":"x"}).status_code == 404
        assert c.put("/secrets/ANTHROPIC_API_KEY", json={"value":123}).status_code == 400
        r = c.put("/secrets/ANTHROPIC_API_KEY", json={"value":"sk-anthropic-secret"})
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "config"
        assert "keyring unavailable" in caplog.text
        assert "ANTHROPIC_API_KEY=sk-anthropic-secret" in (tmp_path / ".env").read_text()
        assert "anthropic" in server.configured_providers()


def test_set_secret_failing_keyring_warns_and_uses_file(monkeypatch, tmp_path, caplog):
    class BrokenKeyring:
        def set_password(self, service, name, value): raise RuntimeError("no keyring")
    monkeypatch.setitem(sys.modules, "keyring", BrokenKeyring())
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"
    summary = set_secret("GROQ_API_KEY", "sk-groq-secret", env_path=env)
    assert summary.source == "config"
    assert "GROQ_API_KEY=sk-groq-secret" in env.read_text()
    assert "keyring unavailable" in caplog.text


def test_secrets_api_falls_back_when_keyring_hangs(monkeypatch, tmp_path):
    class HangingKeyring:
        def get_password(self, service, name): return None
        def set_password(self, service, name, value): threading.Event().wait(1)
        def delete_password(self, service, name): return None
    monkeypatch.setitem(sys.modules, "keyring", HangingKeyring())
    monkeypatch.setenv("NEXUSSY_KEYRING_TIMEOUT_S", "0.01")
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.put("/secrets/OPENROUTER_API_KEY", json={"value":"sk-openrouter-secret"})
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "config"
        assert "OPENROUTER_API_KEY=sk-openrouter-secret" in (tmp_path / ".env").read_text()


def test_secret_updates_invalidate_provider_env_cache(monkeypatch, tmp_path):
    class BrokenKeyring:
        def get_password(self, service, name): raise RuntimeError("no keyring")
        def set_password(self, service, name, value): raise RuntimeError("no keyring")
        def delete_password(self, service, name): raise RuntimeError("no keyring")
    seen=[]
    async def fake_complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        seen.append((_env or {}).get("OPENAI_API_KEY"))
        if "Generate a JSON array" in prompt:
            return ProviderResult('[{"id":"q_name","question":"Name?"},{"id":"q_lang","question":"Language?"},{"id":"q_desc","question":"Description?"},{"id":"q_type","question":"Type?"}]', {"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model})
        return ProviderResult('{"q_name":"Demo","q_lang":"Python","q_desc":"API","q_type":"API"}', {"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model})
    monkeypatch.setitem(sys.modules, "keyring", BrokenKeyring())
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete)
    server.config = load_config({"providers":{"default_model":"openai/gpt-5.5-fast"}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        assert c.put("/secrets/OPENAI_API_KEY", json={"value":"sk-old"}).status_code == 200
        first = c.post("/pipeline/start", json={"project_name":"Cache One","description":"small api","auto_approve_interview":True,"stop_after_stage":"interview","metadata":{"mock_provider":True}}).json()
        _wait_done(c, first["run_id"])
        assert c.put("/secrets/OPENAI_API_KEY", json={"value":"sk-new"}).status_code == 200
        second = c.post("/pipeline/start", json={"project_name":"Cache Two","description":"small api","auto_approve_interview":True,"stop_after_stage":"interview","metadata":{"mock_provider":True}}).json()
        _wait_done(c, second["run_id"])
    assert "sk-old" in seen
    assert seen[-1] == "sk-new"


@pytest.mark.asyncio
async def test_fake_provider_production_path(monkeypatch):
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    result = await complete("design", "hello fake provider", "openai/gpt-5.5-fast", allow_mock=False)
    assert result.usage["provider"] == "fake"
    assert "fake provider design" in result.text


@pytest.mark.asyncio
async def test_file_lock_and_role(tmp_path):
    db = Database(str(tmp_path / "locks.db")); await db.init()
    lock = await claim_file(db, "run", "src/a.py", "backend-abcdef", timeout_s=1, retry_ms=10)
    assert lock.status == "claimed"
    with pytest.raises(TimeoutError):
        await claim_file(db, "run", "src/a.py", "qa-abcdef", timeout_s=.02, retry_ms=5)
    assert enforce_tool(WorkerRole.backend, ToolName.write_file)
    with pytest.raises(PermissionError):
        enforce_tool(WorkerRole.analyst, ToolName.write_file)
    assert enforce_tool(WorkerRole.orchestrator, ToolName.write_file, "./devplan.md")
    with pytest.raises(PermissionError):
        enforce_tool(WorkerRole.orchestrator, ToolName.write_file, "sub/../devplan.md")
    with pytest.raises(PermissionError):
        enforce_tool(WorkerRole.orchestrator, ToolName.write_file, "phase001/file.txt")
    assert await write_requires_lock(db, "run", "src/a.py", "backend-abcdef") == "src/a.py"
    with pytest.raises(PermissionError):
        await write_requires_lock(db, "run", "src/a.py", "frontend-abcdef")


@pytest.mark.asyncio
async def test_file_lock_unique_constraint_only_applies_to_claimed(tmp_path):
    db = Database(str(tmp_path / "locks.db")); await db.init()
    now = datetime.now(timezone.utc).isoformat()
    await db.write(lambda con: con.execute("INSERT INTO file_locks VALUES(?,?,?,?,?,?)", ("run", "src/a.py", "w1", "released", now, now)))
    await db.write(lambda con: con.execute("INSERT INTO file_locks VALUES(?,?,?,?,?,?)", ("run", "src/a.py", "w2", "released", now, now)))
    await db.write(lambda con: con.execute("INSERT INTO file_locks VALUES(?,?,?,?,?,?)", ("run", "src/a.py", "w1", "claimed", now, now)))
    with pytest.raises(sqlite3.IntegrityError):
        await db.write(lambda con: con.execute("INSERT INTO file_locks VALUES(?,?,?,?,?,?)", ("run", "src/a.py", "w2", "claimed", now, now)))


@pytest.mark.asyncio
async def test_claim_file_non_integrity_error_propagates():
    class BrokenDb:
        async def write(self, fn):
            raise sqlite3.OperationalError("disk full")
    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        await claim_file(BrokenDb(), "run", "src/a.py", "w1", timeout_s=1, retry_ms=1)


@pytest.mark.asyncio
async def test_rate_limit_persistence_and_db_pragmas(tmp_path):
    db = Database(str(tmp_path / "state.db")); await db.init()
    con = sqlite3.connect(tmp_path / "state.db")
    assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    required = {"sessions","runs","stage_runs","events","artifacts","checkpoints","workers","worker_tasks","blockers","file_locks","rate_limits","memory_entries"}
    assert required <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    versions = [row[0] for row in con.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions[-1] == CURRENT_SCHEMA_VERSION
    await persist_rate_limit(db, "openai", "openai/x", datetime.now(timezone.utc)+timedelta(seconds=60), "quota")
    assert (await active_rate_limit(db, "openai", "openai/x"))["reason"] == "quota"


@pytest.mark.asyncio
async def test_complete_persists_litellm_429(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "state.db")); await db.init()
    class RateLimitError(Exception):
        status_code = 429
        headers = {"retry-after": "30"}
    async def acompletion(*args, **kwargs):
        raise RateLimitError("rate limit 429")
    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(acompletion=acompletion, RateLimitError=RateLimitError))
    with pytest.raises(RateLimitError):
        await complete("design", "prompt", "openai/gpt-5.5-fast", _env={"OPENAI_API_KEY":"sk-test"}, db=db)
    rows = await db.read("SELECT provider, model, reason FROM rate_limits")
    assert rows == [{"provider":"openai", "model":"openai/gpt-5.5-fast", "reason":"rate limit 429"}]


@pytest.mark.asyncio
async def test_git_worktree_lifecycle(tmp_path):
    repo = tmp_path / "repo"; base = await init_repo(str(repo))
    wt1, br1 = await create_worktree(str(repo), str(tmp_path / "workers"), "w1")
    Path(wt1, "a.txt").write_text("a")
    await commit_worker(wt1, "w1")
    assert (await merge_no_ff(str(repo), br1)).passed
    manifest = await extract_changed_files(str(repo), base, str(repo / ".nexussy" / "artifacts" / "changed-files"))
    assert [f.path for f in manifest.files] == ["a.txt"]
    await prune_worktrees(str(repo))


@pytest.mark.asyncio
async def test_git_changed_files_uses_new_path_for_rename(tmp_path):
    repo = tmp_path / "repo"; base = await init_repo(str(repo))
    (repo / "old.txt").write_text("old")
    await _git(repo, "add", ".")
    await _git(repo, "commit", "-m", "add old")
    base = await _git(repo, "rev-parse", "HEAD")
    (repo / "old.txt").rename(repo / "new.txt")
    await _git(repo, "add", ".")
    await _git(repo, "commit", "-m", "rename")
    manifest = await extract_changed_files(str(repo), base, str(repo / ".nexussy" / "artifacts" / "changed-files"))
    assert [(f.path, f.status) for f in manifest.files] == [("new.txt", "renamed")]


@pytest.mark.asyncio
async def test_pi_rpc_fake_child_and_scrubbing(tmp_path):
    child = tmp_path / "fake_pi.py"
    child.write_text('import sys,json\nprint(json.dumps({"jsonrpc":"2.0","method":"agent.event","params":{"type":"x"}}), flush=True)\nprint("password=secret", file=sys.stderr, flush=True)\n')
    cfg = load_config({"pi":{"command":sys.executable,"args":[str(child)],"max_stdout_line_bytes":200,"shutdown_timeout_s":0}})
    rpc = await spawn_pi_worker(cfg, "run", "worker", "backend", str(tmp_path), str(tmp_path))
    await asyncio.sleep(.2)
    await rpc.stop(timeout_s=.1)
    lines = [f.payload.line for f in rpc.frames]
    assert any(f.payload.parsed for f in rpc.frames)
    assert any("[REDACTED]" in line for line in lines)


@pytest.mark.asyncio
async def test_pi_missing_command_precise_error(tmp_path):
    cfg = load_config({"pi":{"command":"/no/such/pi-nexussy-test","args":[]}})
    with pytest.raises(RuntimeError, match="missing Pi CLI"):
        await spawn_pi_worker(cfg, "run", "backend-abcdef", "backend", str(tmp_path), str(tmp_path))


@pytest.mark.asyncio
async def test_bundled_pi_returns_error_when_local_worker_command_missing_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUSSY_DISABLE_BUNDLED_PI", raising=False)
    cfg = load_config({"pi":{"command":"local-pi-worker","args":[],"shutdown_timeout_s":0}})
    rpc = await spawn_pi_worker(cfg, "run", "backend-abcdef", "backend", str(tmp_path), str(tmp_path))
    req_id = await rpc.request("Build API", "ctx")
    response = await rpc.wait_response(req_id, 5)
    await rpc.stop(timeout_s=.1)
    assert "error" in response
    assert "result" not in response
    assert response["error"]["data"]["status"] == "error"
    assert not (tmp_path / "backend.txt").exists()


def test_pipeline_develop_uses_fake_pi_and_worktrees(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    child = tmp_path / "fake_pi_develop.py"
    child.write_text(
        "import json, os, pathlib, sys\n"
        "line=sys.stdin.readline()\n"
        "msg=json.loads(line)\n"
        "role=os.environ['NEXUSSY_WORKER_ROLE']\n"
        "pathlib.Path(os.environ['NEXUSSY_WORKTREE'], role + '.txt').write_text(role + ' done\\n')\n"
        "print(json.dumps({'jsonrpc':'2.0','method':'agent.event','params':{'type':'content_delta','payload':{'delta':'working'}}}), flush=True)\n"
        "print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'status':'ok'}}), flush=True)\n"
    )
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={
            "project_name":"Develop Fake Pi",
            "description":"Build backend and frontend with tests",
            "auto_approve_interview":True,
            "metadata":{"mock_provider":False,"fake_pi_command":sys.executable,"fake_pi_args":[str(child)]},
        })
        assert r.status_code == 200, r.text
        body = r.json()
        for _ in range(100):
            ev = c.get("/events", params={"run_id": body["run_id"]}).json()
            if ev and ev[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev[-1]["payload"]["final_status"] == "passed", ev[-1]
        arts = c.get("/pipeline/artifacts", params={"session_id":body["session_id"],"run_id":body["run_id"]}).json()["artifacts"]
        assert {a["kind"] for a in arts} >= {"develop_report", "merge_report", "changed_files"}
        changed = c.get("/pipeline/artifacts/changed_files", params={"session_id":body["session_id"]}).json()["content_text"]
        changed_json = json.loads(changed)
        assert sorted(f["path"] for f in changed_json["files"]) == ["backend.txt", "frontend.txt"]
        events = c.get("/events", params={"run_id": body["run_id"]}).json()
        assert sum(1 for e in events if e["type"] == "worker_task") >= 4
        workers = c.get("/swarm/workers", params={"run_id": body["run_id"]}).json()
        assert any(w["role"] == "orchestrator" for w in workers)


def test_develop_pause_resume_requeues_running_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    child = tmp_path / "fake_pi_pause.py"
    child.write_text(
        "import json, os, pathlib, sys, time\n"
        "line=sys.stdin.readline()\n"
        "msg=json.loads(line)\n"
        "role=os.environ['NEXUSSY_WORKER_ROLE']\n"
        "wt=pathlib.Path(os.environ['NEXUSSY_WORKTREE'])\n"
        "marker=wt / '.resumed'\n"
        "if not marker.exists():\n"
        "    marker.write_text('first')\n"
        "    time.sleep(10)\n"
        "else:\n"
        "    (wt / (role + '.txt')).write_text(role + ' resumed\\n')\n"
        "    print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'status':'ok'}}), flush=True)\n"
    )
    server.config = load_config({"swarm":{"default_worker_count":1}, "pi":{"shutdown_timeout_s":0}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Pause Resume","description":"backend","auto_approve_interview":True,"metadata":{"mock_provider":False,"fake_pi_command":sys.executable,"fake_pi_args":[str(child)],"worker_roles":["backend"]}}).json()
        for _ in range(100):
            ev = c.get("/events", params={"run_id": r["run_id"]}).json()
            if any(e["type"] == "worker_task" and e["payload"].get("status") == "running" for e in ev): break
            import time; time.sleep(.05)
        import time; time.sleep(.2)
        assert c.post("/pipeline/pause", json={"run_id":r["run_id"],"reason":"test pause"}).json()["status"] == "paused"
        for _ in range(100):
            ev = c.get("/events", params={"run_id": r["run_id"]}).json()
            if any(e["type"] == "worker_task" and e["payload"].get("status") == "queued" for e in ev): break
            import time; time.sleep(.05)
        assert any(e["type"] == "worker_task" and e["payload"].get("status") == "queued" for e in ev)
        assert c.post("/pipeline/resume", json={"run_id":r["run_id"]}).json()["status"] == "running"
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        statuses = [e["payload"].get("status") for e in ev if e["type"] == "worker_task"]
        assert "queued" in statuses and statuses.count("running") >= 2 and "passed" in statuses


def test_task_skip_emits_worker_task_and_updates_handoff(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Skip Task","description":"small api","auto_approve_interview":True,"stop_after_stage":"plan","metadata":{"mock_provider":True}}).json()
        ev = _wait_done(c, r["run_id"])
        assert ev[-1]["payload"]["final_status"] == "passed"
        asyncio.run(server.engine._persist_worker_task(r["run_id"], "backend-123", "task-123", 1, "Build backend", WorkerTaskStatus.running))
        skipped = c.post("/pipeline/skip", json={"run_id":r["run_id"],"stage":"develop","task_id":"task-123","reason":"user chose alternate path"})
        assert skipped.status_code == 200, skipped.text
        ev = c.get("/events", params={"run_id": r["run_id"]}).json()
        assert any(e["type"] == "worker_task" and e["payload"].get("task_id") == "task-123" and e["payload"].get("status") == "skipped" for e in ev)
        handoff = c.get("/pipeline/artifacts/handoff", params={"session_id":r["session_id"]}).json()["content_text"]
        assert "Skipped task task-123: user chose alternate path" in handoff


def test_blocker_resolution_restores_previous_status(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Blocker Restore","description":"small api","auto_approve_interview":True,"stop_after_stage":"plan","metadata":{"mock_provider":True}}).json()
        _wait_done(c, r["run_id"])
        before = c.get("/pipeline/status", params={"run_id":r["run_id"]}).json()["run"]["status"]
        assert before == "passed"
        warning = c.post("/pipeline/blockers", json={"run_id":r["run_id"],"stage":"develop","severity":"warning","message":"heads up"}).json()
        assert c.get("/pipeline/status", params={"run_id":r["run_id"]}).json()["run"]["status"] == "passed"
        blocker = c.post("/pipeline/blockers", json={"run_id":r["run_id"],"stage":"develop","severity":"blocker","message":"blocked"}).json()
        assert c.get("/pipeline/status", params={"run_id":r["run_id"]}).json()["run"]["status"] == "blocked"
        assert c.post("/pipeline/blockers/resolve", json={"run_id":r["run_id"],"blocker_id":warning["blocker_id"]}).status_code == 200
        assert c.get("/pipeline/status", params={"run_id":r["run_id"]}).json()["run"]["status"] == "blocked"
        assert c.post("/pipeline/blockers/resolve", json={"run_id":r["run_id"],"blocker_id":blocker["blocker_id"]}).status_code == 200
        assert c.get("/pipeline/status", params={"run_id":r["run_id"]}).json()["run"]["status"] == "passed"


def test_develop_merge_conflict_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NEXUSSY_PROVIDER_MODE", "fake")
    child = tmp_path / "fake_pi_conflict.py"
    child.write_text(
        "import json, os, pathlib, sys\n"
        "line=sys.stdin.readline()\n"
        "msg=json.loads(line)\n"
        "role=os.environ['NEXUSSY_WORKER_ROLE']\n"
        "pathlib.Path(os.environ['NEXUSSY_WORKTREE'], 'shared.txt').write_text(role + ' wins\\n')\n"
        "print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'status':'ok'}}), flush=True)\n"
    )
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Conflict","description":"backend frontend","auto_approve_interview":True,"metadata":{"mock_provider":False,"fake_pi_command":sys.executable,"fake_pi_args":[str(child)]}}).json()
        for _ in range(100):
            ev = c.get("/events", params={"run_id": r["run_id"]}).json()
            if ev and ev[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev[-1]["payload"]["final_status"] == "failed"
        assert any(e["type"] == "git_event" and e["payload"].get("action") == "merge_conflict" for e in ev)
        merge = c.get("/pipeline/artifacts/merge_report", params={"session_id":r["session_id"]}).json()["content_text"]
        assert json.loads(merge)["passed"] is False


@pytest.mark.asyncio
async def test_sse_slow_client_receives_terminal_error(tmp_path):
    db = Database(str(tmp_path / "slow.db")); await db.init()
    cfg = load_config({"sse":{"client_queue_max_events":1}})
    engine = Engine(db, cfg)
    run = RunSummary(session_id="sid", run_id="rid", status=RunStatus.running)
    await db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",("rid","sid","running","interview",now := datetime.now(timezone.utc).isoformat(),None,run.usage.model_dump_json())))
    q = asyncio.Queue(maxsize=1); engine.queues.setdefault("rid", set()).add(q)
    await engine.emit(SSEEventType.run_started, "sid", "rid", run)
    await engine.emit(SSEEventType.done, "sid", "rid", {"final_status":"passed"})
    terminal = await q.get()
    assert terminal.type == "pipeline_error"
    assert terminal.payload["error_code"] == "sse_client_slow"
    assert q not in engine.queues.get("rid", set())
    persisted = await engine.replay("rid")
    assert any(e.type == "pipeline_error" and e.payload["error_code"] == "sse_client_slow" for e in persisted)


@pytest.mark.asyncio
async def test_persist_event_embeds_sequence_in_single_write(tmp_path):
    class CountingDatabase(Database):
        def __init__(self, path):
            super().__init__(path)
            self.write_count = 0
        async def write(self, fn):
            self.write_count += 1
            return await super().write(fn)
    db = CountingDatabase(str(tmp_path / "events.db")); await db.init()
    engine = Engine(db, load_config())
    before = db.write_count
    env = EventEnvelope(sequence=0,type=SSEEventType.run_started,session_id="sid",run_id="rid",payload={"ok": True})
    await engine._persist_event(env)
    assert db.write_count - before == 1
    rows = await db.read("SELECT sequence,payload_json FROM events WHERE event_id=?", (env.event_id,))
    assert rows[0]["sequence"] == 1
    assert json.loads(rows[0]["payload_json"])["sequence"] == 1


def test_path_and_secret_security(tmp_path):
    from nexussy.security import sanitize_path
    root = tmp_path / "root"; root.mkdir(); outside = tmp_path / "outside"; outside.mkdir()
    with pytest.raises(ValueError): sanitize_path(str(outside / "x"), [str(root)])
    link = root / "link"; link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError): sanitize_path(str(link / "x"), [str(root)])
    assert "[REDACTED]" in scrub_log("OPENAI_API_KEY=sk-secretsecretsecret ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAfoo")


def test_public_path_schemas_reject_escape_paths():
    with pytest.raises(Exception):
        ArtifactRef(kind="devplan", path="../devplan.md", sha256="a")
    from nexussy.api.schemas import FileLock, ChangedFile
    with pytest.raises(Exception):
        FileLock(path="/tmp/x", worker_id="w", run_id="r")
    with pytest.raises(Exception):
        ChangedFile(path="a/../../x", status="modified")


def test_safe_write_keeps_tmp_on_validation_failure(tmp_path):
    (tmp_path / "handoff.md").write_text("original")
    with pytest.raises(ValueError):
        safe_write(str(tmp_path), "handoff.md", "missing anchors")
    assert (tmp_path / "handoff.md").read_text() == "original"
    assert (tmp_path / "handoff.md.tmp").read_text() == "missing anchors"


@pytest.mark.asyncio
async def test_project_db_initialized_for_session(tmp_path):
    db = Database(str(tmp_path / "global.db")); await db.init()
    cfg = load_config({"projects_dir": str(tmp_path / "projects")})
    detail = await Engine(db, cfg).create_session(PipelineStartRequest(project_name="DB Demo", description="x"))
    project_db = Path(detail.project_root) / ".nexussy" / "state.db"
    assert project_db.exists()
    con = sqlite3.connect(project_db)
    try:
        assert con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
    finally:
        con.close()


@pytest.mark.asyncio
async def test_provider_fallback_emits_retryable_pipeline_error(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "state.db")); await db.init()
    cfg = load_config({"projects_dir": str(tmp_path / "projects"), "providers":{"default_model":"openai/gpt-5.5-fast", "allow_fallback":True}})
    def available(model, allow_mock=False):
        return model == "openai/gpt-5.5-fast"
    async def fake_complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        return ProviderResult("[]", {"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"fake","model":model})
    monkeypatch.setattr("nexussy.pipeline.engine.model_available", available)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete)
    engine = Engine(db, cfg)
    res = await engine.start(PipelineStartRequest(project_name="Fallback", description="small api", stop_after_stage="interview", auto_approve_interview=True, model_overrides={StageName.interview:"missing/model"}))
    events = await engine.replay(res.run_id)
    assert any(e.type == "pipeline_error" and e.payload["retryable"] is True and e.payload["details"]["fallback_model"] == "openai/gpt-5.5-fast" for e in events)
    engine.tasks[res.run_id].cancel()


@pytest.mark.asyncio
async def test_worker_tool_permission_failure_emits_tool_output(tmp_path):
    db = Database(str(tmp_path / "state.db")); await db.init()
    cfg = load_config({"projects_dir": str(tmp_path / "projects")})
    engine = Engine(db, cfg)
    now = datetime.now(timezone.utc).isoformat()
    await db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",("rid","sid","running","develop",now,None,"{}")))
    worker = server.Worker(worker_id="analyst-1", run_id="rid", role=WorkerRole.analyst, status=server.WorkerStatus.running, worktree_path=str(tmp_path), branch_name="worker/analyst-1", model="openai/gpt-5.5-fast")
    await db.write(lambda con: con.execute("INSERT INTO workers VALUES(?,?,?,?,?,?,?,?,?,?,?)",(worker.worker_id,worker.run_id,worker.role,worker.status,worker.task_id,worker.worktree_path,worker.branch_name,worker.pid,worker.usage.model_dump_json(),None,worker.model_dump_json())))
    result = await engine.execute_worker_tool("rid", "analyst-1", ToolName.write_file, {"path":"src/app.py"})
    assert result["success"] is False
    events = await engine.replay("rid")
    call = next(e for e in events if e.type == "tool_call")
    out = next(e for e in events if e.type == "tool_output")
    assert call.payload["call_id"] == out.payload["call_id"]
    assert call.payload["stage"] == "develop"
    assert call.payload["tool_name"] == "write_file"
    assert call.payload["arguments"] == {"path":"src/app.py"}
    assert out.payload["success"] is False
    assert out.payload["error"]


def test_existing_repo_path_rejects_symlink_escape_and_copies_safe_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "secret.txt").write_text("secret")
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "README.md").write_text("ok")
    subprocess_run = __import__("subprocess").run
    subprocess_run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "escape").symlink_to(outside / "secret.txt")
    server.config = load_config({"projects_dir": str(tmp_path / "projects")})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        bad = c.post("/sessions", json={"project_name":"Bad Import","description":"x","existing_repo_path":str(repo)})
        assert bad.status_code == 400
        (repo / "escape").unlink()
        good = c.post("/sessions", json={"project_name":"Good Import","description":"x","existing_repo_path":str(repo)})
        assert good.status_code == 200, good.text
        main = Path(good.json()["main_worktree"])
        assert (main / "README.md").read_text() == "ok"


def test_unknown_resources_return_404(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config({"projects_dir": str(tmp_path / "projects")})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    with TestClient(app) as c:
        assert c.get("/pipeline/runs/nope/stream").status_code == 404
        assert c.get("/events", params={"run_id":"nope"}).status_code == 404
        assert c.delete("/memory/nope").status_code == 404
        assert c.get("/pipeline/artifacts", params={"session_id":"nope"}).status_code == 404
        assert c.post("/swarm/spawn", json={"run_id":"nope","role":"backend","task":"x"}).status_code == 404


def test_worker_stream_filters_replay_to_requested_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config({"projects_dir": str(tmp_path / "projects"), "sse":{"heartbeat_interval_s":60}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    async def seed():
        await server.db.init()
        now = datetime.now(timezone.utc).isoformat()
        await server.db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",("rid","sid","running","develop",now,None,"{}")))
        for wid in ("backend-1", "frontend-1"):
            worker = Worker(worker_id=wid, run_id="rid", role=WorkerRole.backend, status=WorkerStatus.running, worktree_path=str(tmp_path), branch_name=f"worker/{wid}", model="openai/gpt-5.5-fast")
            await server.db.write(lambda con, worker=worker: con.execute("INSERT INTO workers VALUES(?,?,?,?,?,?,?,?,?,?,?)",(worker.worker_id,worker.run_id,worker.role,worker.status,worker.task_id,worker.worktree_path,worker.branch_name,worker.pid,worker.usage.model_dump_json(),None,worker.model_dump_json())))
        await server.engine.emit(SSEEventType.worker_stream, "sid", "rid", server.WorkerStreamPayload(worker_id="frontend-1", stream_kind="rpc", line="front"))
        await server.engine.emit(SSEEventType.worker_stream, "sid", "rid", server.WorkerStreamPayload(worker_id="backend-1", stream_kind="rpc", line="back"))
    asyncio.run(seed())
    class Req:
        headers = {}
        query_params = {}
        path_params = {"worker_id":"backend-1"}
        url = types.SimpleNamespace(path="/swarm/workers/backend-1/stream")
    async def first_frame():
        resp = await server.stream(Req())
        frame = await anext(resp.body_iterator)
        await resp.body_iterator.aclose()
        return frame
    body = json.loads(asyncio.run(first_frame()).split("data: ", 1)[1].split("\n", 1)[0])
    assert body["payload"]["worker_id"] == "backend-1"
    assert body["payload"]["line"] == "back"
    with TestClient(app) as c:
        assert c.get("/swarm/workers/missing/stream").status_code == 404


@pytest.mark.asyncio
async def test_worker_rpc_timeout_uses_pause_state_captured_at_timeout(monkeypatch, tmp_path):
    class FakeRpc:
        frames = []
        async def request(self, title, context): return "req-1"
        async def wait_response(self, req_id, timeout_s):
            calls["wait"] += 1
            if calls["wait"] == 1:
                raise TimeoutError("paused timeout")
        async def stop(self, timeout_s):
            engine.paused.pop("rid", None)
    async def fake_spawn(*args, **kwargs): return FakeRpc()
    calls = {"wait": 0}
    db = Database(str(tmp_path / "state.db")); await db.init()
    cfg = load_config({"swarm":{"worker_task_timeout_s":1}, "pi":{"shutdown_timeout_s":0}})
    engine = Engine(db, cfg)
    now = datetime.now(timezone.utc).isoformat()
    await db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",("rid","sid","running","develop",now,None,"{}")))
    worker = Worker(worker_id="backend-1", run_id="rid", role=WorkerRole.backend, status=WorkerStatus.running, task_id="task-1", task_title="Build backend", worktree_path=str(tmp_path), branch_name="worker/backend-1", model="openai/gpt-5.5-fast")
    engine.paused["rid"] = True
    monkeypatch.setattr("nexussy.pipeline.engine.spawn_pi_worker", fake_spawn)
    await engine._run_worker_rpc("rid", "sid", worker, 1, cfg, WorkerRole.backend, tmp_path, tmp_path)
    rows = await db.read("SELECT status FROM worker_tasks WHERE task_id=?", ("task-1",))
    assert rows[-1]["status"] == WorkerTaskStatus.running.value


@pytest.mark.asyncio
async def test_file_lock_claim_emits_claimed_and_waiting(tmp_path):
    db = Database(str(tmp_path / "state.db")); await db.init()
    seen=[]
    async def emit(kind, lock):
        seen.append((kind, lock.status))
    await claim_file(db, "rid", "src/app.py", "w1", emit=emit)
    with pytest.raises(TimeoutError):
        await claim_file(db, "rid", "src/app.py", "w2", timeout_s=0, retry_ms=1, emit=emit)
    assert ("file_claimed", "claimed") in seen
    assert ("file_lock_waiting", "waiting") in seen


@pytest.mark.asyncio
async def test_mcp_stdio_lists_tools():
    from nexussy.mcp import call_stdio
    class Reader:
        def __init__(self): self.lines=[b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n', b'']
        async def readline(self): return self.lines.pop(0)
    class Writer:
        def __init__(self): self.data=b""
        def write(self, b): self.data += b
        async def drain(self): pass
        def close(self): pass
    writer=Writer()
    await call_stdio(Reader(), writer)
    response=json.loads(writer.data.decode().splitlines()[0])
    assert response["result"]["tools"]


@pytest.mark.asyncio
async def test_mcp_stdio_error_codes_and_initialized_notification():
    from nexussy.mcp import call_stdio
    class Reader:
        def __init__(self):
            self.lines=[
                b'{bad json\n',
                b'{"jsonrpc":"2.0","id":2}\n',
                b'{"jsonrpc":"2.0","id":3,"method":"missing/method"}\n',
                b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
                b'',
            ]
        async def readline(self): return self.lines.pop(0)
    class Writer:
        def __init__(self): self.data=b""
        def write(self, b): self.data += b
        async def drain(self): pass
        def close(self): pass
    writer=Writer()
    await call_stdio(Reader(), writer)
    responses=[json.loads(line) for line in writer.data.decode().splitlines()]
    assert [r["error"]["code"] for r in responses] == [-32700, -32600, -32601]


@pytest.mark.asyncio
async def test_pi_rpc_request_without_stdin_raises_runtime_error():
    proc = types.SimpleNamespace(stdin=None)
    with pytest.raises(RuntimeError, match="stdin"):
        await PiRPCProcess(proc).request("task")
