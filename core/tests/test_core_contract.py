import asyncio, json, os, sqlite3, sys, threading, types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from nexussy.api.schemas import ErrorResponse, PipelineStartRequest, EventEnvelope, RunSummary, RunStatus, SSEEventType, ArtifactRef
from nexussy.api import server
from nexussy.api.server import app
from nexussy.artifacts.store import safe_write
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.security import sanitize_relative_path, scrub_log
from nexussy.swarm.locks import claim_file
from nexussy.swarm.roles import enforce_tool
from nexussy.api.schemas import WorkerRole, ToolName
from nexussy.providers import active_rate_limit, complete, persist_rate_limit, select_stage_model
from nexussy.swarm.gitops import init_repo, create_worktree, commit_worker, merge_no_ff, extract_changed_files, prune_worktrees
from nexussy.swarm.locks import write_requires_lock
from nexussy.swarm.pi_rpc import spawn_pi_worker
from nexussy.pipeline.engine import Engine


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
        sanitize_relative_path("../x")
    assert "[REDACTED]" in scrub_log("Authorization: Bearer abc.def.ghi password=secret")


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


def test_route_validation_error_is_normalized(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    with TestClient(app) as c:
        r = c.post("/pipeline/start", json={"project_name":"Bad","description":"x","unexpected":True})
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and body["error_code"] == "validation_error"
        assert body["details"]["errors"]


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
        r2 = c.post("/pipeline/start", json={"project_name":"ReviewFail","description":"small api with tests","auto_approve_interview":True,"stop_after_stage":"review","metadata":{"force_review_fail":True}}).json()
        for _ in range(100):
            ev2 = c.get("/events", params={"run_id": r2["run_id"]}).json()
            if ev2 and ev2[-1]["type"] == "done": break
            import time; time.sleep(.05)
        assert ev2[-1]["payload"]["final_status"] == "failed"
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "plan" for e in ev2)


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
        assert secret not in r.text
        listed = c.get("/secrets").json()
        assert any(x["name"] == "OPENAI_API_KEY" and x["source"] == "keyring" and x["configured"] for x in listed)
        assert secret not in json.dumps(listed)
        assert c.delete("/secrets/OPENAI_API_KEY").status_code == 200
        assert c.delete("/secrets/OPENAI_API_KEY").status_code == 404


def test_secrets_api_falls_back_to_env_file_and_validates(monkeypatch, tmp_path):
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
        assert "ANTHROPIC_API_KEY=sk-anthropic-secret" in (tmp_path / ".env").read_text()
        assert "anthropic" in server.configured_providers()


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
    assert await write_requires_lock(db, "run", "src/a.py", "backend-abcdef") == "src/a.py"
    with pytest.raises(PermissionError):
        await write_requires_lock(db, "run", "src/a.py", "frontend-abcdef")


@pytest.mark.asyncio
async def test_rate_limit_persistence_and_db_pragmas(tmp_path):
    db = Database(str(tmp_path / "state.db")); await db.init()
    con = sqlite3.connect(tmp_path / "state.db")
    assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    required = {"sessions","runs","stage_runs","events","artifacts","checkpoints","workers","worker_tasks","blockers","file_locks","rate_limits","memory_entries"}
    assert required <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    await persist_rate_limit(db, "openai", "openai/x", datetime.now(timezone.utc)+timedelta(seconds=60), "quota")
    assert (await active_rate_limit(db, "openai", "openai/x"))["reason"] == "quota"


def test_git_worktree_lifecycle(tmp_path):
    repo = tmp_path / "repo"; base = init_repo(str(repo))
    wt1, br1 = create_worktree(str(repo), str(tmp_path / "workers"), "w1")
    Path(wt1, "a.txt").write_text("a")
    commit_worker(wt1, "w1")
    assert merge_no_ff(str(repo), br1).passed
    manifest = extract_changed_files(str(repo), base, str(repo / ".nexussy" / "artifacts" / "changed-files"))
    assert [f.path for f in manifest.files] == ["a.txt"]
    prune_worktrees(str(repo))


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
async def test_bundled_pi_fallback_when_external_pi_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUSSY_DISABLE_BUNDLED_PI", raising=False)
    cfg = load_config({"pi":{"command":"pi","args":[],"shutdown_timeout_s":0}})
    rpc = await spawn_pi_worker(cfg, "run", "backend-abcdef", "backend", str(tmp_path), str(tmp_path))
    req_id = await rpc.request("Build API", "ctx")
    response = await rpc.wait_response(req_id, 5)
    await rpc.stop(timeout_s=.1)
    assert response["result"]["status"] == "ok"
    assert (tmp_path / "backend.txt").exists()


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


def test_path_and_secret_security(tmp_path):
    from nexussy.security import sanitize_path
    root = tmp_path / "root"; root.mkdir(); outside = tmp_path / "outside"; outside.mkdir()
    with pytest.raises(ValueError): sanitize_path(str(outside / "x"), [str(root)])
    link = root / "link"; link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError): sanitize_path(str(link / "x"), [str(root)])
    assert "[REDACTED]" in scrub_log("OPENAI_API_KEY=sk-secretsecretsecret ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAfoo")
