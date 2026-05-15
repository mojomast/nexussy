from datetime import datetime, timezone

import pytest

from nexussy.api.schemas import SSEEventType, StageName, ToolOutputPayload, Worker, WorkerRole, WorkerStatus
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine
from nexussy.pipeline.stages.develop import run_worker_rpc
from nexussy.swarm.pi_rpc import PiFrame


@pytest.mark.asyncio
async def test_worker_permission_denial_frame_emits_tool_output_sse(tmp_path):
    db = Database(str(tmp_path / "state.db"))
    await db.init()
    engine = Engine(db, load_config({"pi": {"shutdown_timeout_s": 0}}))
    await db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("rid", "sid", "running", "develop", datetime.now(timezone.utc).isoformat(), None, "{}")))

    payload = ToolOutputPayload(call_id="call-1", stage=StageName.develop, success=False, error="forbidden", worker_id="analyst-1")

    class FakeRpc:
        worker_id = "analyst-1"
        frames = [PiFrame("tool_output", payload)]

        async def request(self, title, context):
            return "req-1"

        async def wait_response(self, req_id, timeout_s):
            return {"result": {"status": "ok"}}

        async def stop(self, timeout_s):
            return None

    async def fake_spawn(*args, **kwargs):
        return FakeRpc()

    worker = Worker(worker_id="analyst-1", run_id="rid", role=WorkerRole.analyst, status=WorkerStatus.running, task_id="task-abc123", task_title="Analyze", worktree_path=str(tmp_path), branch_name="worker/analyst-1", model="openai/gpt-5.5-fast")

    await run_worker_rpc(engine, "rid", "sid", worker, 1, engine.config, WorkerRole.analyst, tmp_path, tmp_path, spawn_fn=fake_spawn)

    events = await engine.replay("rid")
    out = next(e for e in events if e.type == SSEEventType.tool_output)
    assert out.payload["call_id"] == "call-1"
    assert out.payload["stage"] == "develop"
    assert out.payload["success"] is False
    assert out.payload["error"] == "forbidden"
    assert out.payload["worker_id"] == "analyst-1"
