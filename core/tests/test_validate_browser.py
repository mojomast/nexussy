import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from nexussy.api.schemas import ArtifactRef, NexussyConfig, ValidateBrowserStageConfig
from nexussy.api import server
from nexussy.api.server import app
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine
from nexussy.pipeline.stages import validate_browser


class _Session:
    session_id = "sid-1"


class _Detail:
    session = _Session()


class _Engine:
    def __init__(self, cfg):
        self.config = cfg
        self.saved = []

    async def _save_art(self, run_id, session_id, root, kind, text, phase=None):
        self.saved.append({"run_id": run_id, "session_id": session_id, "kind": kind, "text": text})
        return ArtifactRef(kind=kind, path=f".nexussy/artifacts/{kind}.json", sha256="abc", bytes=len(text))


def _engine(validate_browser_cfg):
    return _Engine(NexussyConfig.model_validate({"stages": {"validate_browser": validate_browser_cfg}}))


def test_validate_browser_config_defaults_disabled(monkeypatch):
    for key in (
        "NEXUSSY_VALIDATE_BROWSER_ENABLED",
        "NEXUSSY_VALIDATE_BROWSER_COMMAND",
        "NEXUSSY_VALIDATE_BROWSER_TARGET_URL",
        "NEXUSSY_VALIDATE_BROWSER_TIMEOUT_S",
        "NEXUSSY_VALIDATE_BROWSER_FAILURE_POLICY",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = load_config()

    assert cfg.stages.validate_browser.enabled is False
    assert cfg.stages.validate_browser.command is None
    assert cfg.stages.validate_browser.target_url is None
    assert cfg.stages.validate_browser.timeout_s == 60
    assert cfg.stages.validate_browser.failure_policy == "skip"


def test_validate_browser_config_accepts_safe_values():
    cfg = NexussyConfig.model_validate(
        {
            "stages": {
                "validate_browser": {
                    "enabled": True,
                    "command": "browser-harness",
                    "target_url": "http://127.0.0.1:7772/",
                    "timeout_s": 30,
                    "failure_policy": "fail",
                }
            }
        }
    )

    assert cfg.stages.validate_browser.enabled is True
    assert cfg.stages.validate_browser.command == "browser-harness"
    assert cfg.stages.validate_browser.target_url == "http://127.0.0.1:7772/"
    assert cfg.stages.validate_browser.timeout_s == 30
    assert cfg.stages.validate_browser.failure_policy == "fail"


def test_validate_browser_config_rejects_extra_and_unsafe_values():
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"enabled": False, "unexpected": True})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"command": "   "})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"target_url": ""})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"timeout_s": 0})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"timeout_s": 601})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"failure_policy": "warn"})


def test_validate_browser_config_env_overrides(monkeypatch):
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_ENABLED", "true")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_COMMAND", "browser-harness")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_TARGET_URL", "http://127.0.0.1:7772/")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_TIMEOUT_S", "45")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_FAILURE_POLICY", "fail")

    cfg = load_config()

    assert cfg.stages.validate_browser.enabled is True
    assert cfg.stages.validate_browser.command == "browser-harness"
    assert cfg.stages.validate_browser.target_url == "http://127.0.0.1:7772/"
    assert cfg.stages.validate_browser.timeout_s == 45
    assert cfg.stages.validate_browser.failure_policy == "fail"


@pytest.mark.asyncio
async def test_validate_browser_stage_disabled_skips_without_runner(tmp_path):
    engine = _engine({"enabled": False})

    refs = await validate_browser.run(engine, None, _Detail(), "run-1", None, str(tmp_path), {}, False)

    assert refs[0].kind == "validate_browser_report"
    report = NexussyConfig.model_validate(engine.config.model_dump()).model_dump()  # sanity: config remains valid
    assert report["stages"]["validate_browser"]["enabled"] is False
    saved = engine.saved[0]["text"]
    assert '"passed": true' in saved
    assert '"skipped": true' in saved
    assert "validate_browser disabled" in saved


@pytest.mark.asyncio
async def test_validate_browser_stage_missing_command_skips_or_fails(tmp_path):
    skip_engine = _engine({"enabled": True, "command": "definitely-missing-browser-harness", "target_url": "http://127.0.0.1:7772/", "failure_policy": "skip"})
    fail_engine = _engine({"enabled": True, "command": "definitely-missing-browser-harness", "target_url": "http://127.0.0.1:7772/", "failure_policy": "fail"})

    await validate_browser.run(skip_engine, None, _Detail(), "run-1", None, str(tmp_path), {}, False)
    await validate_browser.run(fail_engine, None, _Detail(), "run-2", None, str(tmp_path), {}, False)

    assert '"passed": true' in skip_engine.saved[0]["text"]
    assert '"skipped": true' in skip_engine.saved[0]["text"]
    assert '"passed": false' in fail_engine.saved[0]["text"]
    assert '"skipped": false' in fail_engine.saved[0]["text"]


@pytest.mark.asyncio
async def test_validate_browser_stage_runs_fake_browser_harness(tmp_path):
    engine = _engine({"enabled": True, "command": "/fake/browser-harness", "target_url": "http://127.0.0.1:7772/", "timeout_s": 15})
    calls = []

    async def runner(args, timeout_s):
        calls.append((args, timeout_s))
        if args[-1] == "--doctor":
            return validate_browser.CommandResult(0, "doctor ok", "")
        return validate_browser.CommandResult(0, '{"page":{"title":"ok"},"events":[]}\n', "")

    await validate_browser.run(engine, None, _Detail(), "run-1", None, str(tmp_path), {}, False, command_runner=runner)

    assert calls[0] == (["/fake/browser-harness", "--doctor"], 15)
    assert calls[1][0][0:2] == ["/fake/browser-harness", "-c"]
    assert "new_tab('http://127.0.0.1:7772/')" in calls[1][0][2]
    assert '"passed": true' in engine.saved[0]["text"]
    assert '"findings": []' in engine.saved[0]["text"]


@pytest.mark.asyncio
async def test_validate_browser_stage_reports_console_errors(tmp_path):
    engine = _engine({"enabled": True, "command": "/fake/browser-harness", "target_url": "http://127.0.0.1:7772/"})

    async def runner(args, timeout_s):
        if args[-1] == "--doctor":
            return validate_browser.CommandResult(0, "doctor ok", "")
        payload = {"events": [{"method": "Runtime.consoleAPICalled", "params": {"type": "error", "args": [{"value": "boom"}]}}]}
        return validate_browser.CommandResult(0, json_dumps(payload), "")

    await validate_browser.run(engine, None, _Detail(), "run-1", None, str(tmp_path), {}, False, command_runner=runner)

    assert '"passed": false' in engine.saved[0]["text"]
    assert "boom" in engine.saved[0]["text"]


def json_dumps(value):
    import json

    return json.dumps(value) + "\n"


def _wait_done(client, run_id):
    for _ in range(100):
        events = client.get("/events", params={"run_id": run_id}).json()
        if events and events[-1]["type"] == "done":
            return events
        import time

        time.sleep(0.05)
    return events


def test_pipeline_runs_validate_browser_after_develop_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))

    async def fake_run_command(args, timeout_s):
        if args[-1] == "--doctor":
            return validate_browser.CommandResult(0, "doctor ok", "")
        return validate_browser.CommandResult(0, json_dumps({"events": []}), "")

    monkeypatch.setattr(validate_browser, "_run_command", fake_run_command)
    server.config = load_config({"stages": {"validate_browser": {"enabled": True, "command": "/fake/browser-harness", "target_url": "http://127.0.0.1:7772/"}}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)

    with TestClient(app) as client:
        response = client.post("/pipeline/start", json={"project_name": "Browser Validation", "description": "small api", "auto_approve_interview": True, "metadata": {"mock_provider": True}})
        assert response.status_code == 200, response.text
        body = response.json()
        events = _wait_done(client, body["run_id"])

        assert events[-1]["payload"]["final_status"] == "passed"
        transitions = [event["payload"]["to_stage"] for event in events if event["type"] == "stage_transition"]
        assert transitions[-2:] == ["develop", "validate_browser"]
        status = client.get("/pipeline/status", params={"run_id": body["run_id"]}).json()
        assert status["run"]["current_stage"] == "validate_browser"
        assert any(stage["stage"] == "validate_browser" and stage["status"] == "passed" for stage in status["stages"])
        report = client.get("/pipeline/artifacts/validate_browser_report", params={"session_id": body["session_id"]}).json()
        assert report["ok"] is True
        assert '"passed": true' in report["content_text"]


def test_pipeline_validate_browser_failure_fails_run(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))

    async def fake_run_command(args, timeout_s):
        if args[-1] == "--doctor":
            return validate_browser.CommandResult(0, "doctor ok", "")
        payload = {"events": [{"method": "Runtime.consoleAPICalled", "params": {"type": "error", "args": [{"value": "boom"}]}}]}
        return validate_browser.CommandResult(0, json_dumps(payload), "")

    monkeypatch.setattr(validate_browser, "_run_command", fake_run_command)
    server.config = load_config({"stages": {"validate_browser": {"enabled": True, "command": "/fake/browser-harness", "target_url": "http://127.0.0.1:7772/"}}})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)

    with TestClient(app) as client:
        response = client.post("/pipeline/start", json={"project_name": "Browser Validation Fail", "description": "small api", "auto_approve_interview": True, "metadata": {"mock_provider": True}})
        assert response.status_code == 200, response.text
        body = response.json()
        events = _wait_done(client, body["run_id"])

        assert events[-1]["payload"]["final_status"] == "failed"
        assert any(event["type"] == "stage_status" and event["payload"].get("stage") == "validate_browser" and event["payload"].get("status") == "failed" for event in events)
