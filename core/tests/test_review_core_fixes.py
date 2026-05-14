import json

import pytest
from starlette.testclient import TestClient

from nexussy.api import server
from nexussy.api.schemas import ToolName, Worker, WorkerRole, WorkerStatus
from nexussy.swarm.locks import claim_file


@pytest.mark.asyncio
async def test_execute_worker_tool_reads_writes_and_emits_progress(isolated_engine, tmp_path):
    run_id = "run-tool"
    session_id = "session-tool"
    worktree = tmp_path / "wt"
    worktree.mkdir()
    await isolated_engine.db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, session_id, "running", "develop", "2026-01-01T00:00:00+00:00", None, "{}")))
    worker = Worker(worker_id="backend-abcdef", run_id=run_id, role=WorkerRole.backend, status=WorkerStatus.running, worktree_path=str(worktree), branch_name="worker/backend-abcdef", model="mock/model")
    await isolated_engine._persist_worker(worker)
    await claim_file(isolated_engine.db, run_id, "out.txt", worker.worker_id)

    write = await isolated_engine.execute_worker_tool(run_id, worker.worker_id, ToolName.write_file, {"path": "out.txt", "content": "hello"})
    read = await isolated_engine.execute_worker_tool(run_id, worker.worker_id, ToolName.read_file, {"path": "out.txt"})
    bash = await isolated_engine.execute_worker_tool(run_id, worker.worker_id, ToolName.bash, {"command": "printf ok"})

    assert write["success"] is True
    assert json.loads(read["result_text"])["content"] == "hello"
    assert json.loads(bash["result_text"])["stdout"] == "ok"
    events = await isolated_engine.db.read("SELECT type FROM events WHERE run_id=?", (run_id,))
    assert "tool_progress" in [e["type"] for e in events]


@pytest.mark.asyncio
async def test_graph_includes_workers_artifacts_tasks_and_locks(isolated_engine):
    sid = "session-graph"
    rid = "run-graph"
    worker = Worker(worker_id="backend-abc123", run_id=rid, role=WorkerRole.backend, status=WorkerStatus.running, worktree_path="/tmp/wt", branch_name="worker/backend-abc123", model="mock/model", task_id="task-abc123", task_title="Build API")
    await isolated_engine.db.write(lambda con: con.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?)", (sid, "graph", "Graph", "running", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}")))
    await isolated_engine.db.write(lambda con: con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (rid, sid, "running", "develop", "2026-01-01T00:00:00+00:00", None, "{}")))
    await isolated_engine.db.write(lambda con: con.execute("INSERT INTO stage_runs VALUES(?,?,?,?,?,?,?)", (rid, "develop", "running", 1, None, None, None)))
    await isolated_engine._persist_worker(worker)
    await isolated_engine._persist_worker_task(rid, worker.worker_id, worker.task_id, 1, worker.task_title, "running")
    await isolated_engine.db.write(lambda con: con.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)", (rid, "develop_report", ".nexussy/artifacts/develop_report.json", "abc", 2, "2026-01-01T00:00:00+00:00", "{}", None)))
    await claim_file(isolated_engine.db, rid, "src/app.py", worker.worker_id)

    client = TestClient(server.app)
    graph = client.get("/graph", params={"run_id": rid}).json()

    kinds = {node["kind"] for node in graph["nodes"]}
    assert {"session", "run", "stage", "worker", "artifact", "task", "file"}.issubset(kinds)
    assert any(edge["kind"] == "has_stage" for edge in graph["edges"])
