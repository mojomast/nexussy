from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from nexussy.api import server
from nexussy.api.server import app
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.mcp import _worker_spawn
from nexussy.pipeline.engine import Engine


@pytest.mark.asyncio
async def test_mcp_worker_spawn_denies_non_orchestrator_when_role_context_exists(tmp_path):
    db = Database(str(tmp_path / "state.db"))
    await db.init()
    engine = Engine(db, load_config({"projects_dir": str(tmp_path / "projects")}))
    await db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("rid", "sid", "running", "develop", datetime.now(timezone.utc).isoformat(), None, "{}")))

    with pytest.raises(PermissionError):
        await _worker_spawn({"run_id": "rid", "role": "backend", "task": "impl", "requester_role": "backend"}, engine=engine, db=db)

    worker = await _worker_spawn({"run_id": "rid", "role": "backend", "task": "impl", "requester_role": "orchestrator"}, engine=engine, db=db)
    assert worker.role == "backend"


def test_api_worker_spawn_denies_non_orchestrator_header(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    server.config = load_config({"projects_dir": str(tmp_path / "projects")})
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)

    with TestClient(app) as client:
        started = client.post("/pipeline/start", json={"project_name": "Spawn Guard", "description": "small api", "auto_approve_interview": True, "stop_after_stage": "design", "metadata": {"mock_provider": True}})
        assert started.status_code == 200, started.text
        rid = started.json()["run_id"]

        denied = client.post("/swarm/spawn", headers={"X-Nexussy-Worker-Role": "backend"}, json={"run_id": rid, "role": "backend", "task": "impl"})
        assert denied.status_code == 403

        allowed = client.post("/swarm/spawn", headers={"X-Nexussy-Worker-Role": "orchestrator"}, json={"run_id": rid, "role": "backend", "task": "impl"})
        assert allowed.status_code == 200, allowed.text

        task = server.engine.tasks.get(rid)
        if task:
            task.cancel()
