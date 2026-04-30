import json
import types

import pytest

from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine


def _devplan_markdown() -> str:
    return """# Plan

<!-- PROGRESS_LOG_START -->
- start
<!-- PROGRESS_LOG_END -->

<!-- NEXT_TASK_GROUP_START -->
- [ ] T-001: Build API
  - acceptance: tests pass
  - files: core/nexussy/api/server.py
<!-- NEXT_TASK_GROUP_END -->
"""


async def _run_plan(tmp_path, provider_text: str, validation: str = "repair"):
    from nexussy.pipeline.stages import plan

    db = Database(str(tmp_path / "state.db"))
    await db.init()
    engine = Engine(db, load_config(overrides={"stages": {"plan": {"devplan_task_validation": validation}}}))
    root = tmp_path / "project"
    root.mkdir()

    async def complete(st, sid, run_id, prompt, selected_models, allow_mock):
        return provider_text

    engine._provider_text = complete
    detail = types.SimpleNamespace(session=types.SimpleNamespace(session_id="sid"))
    req = types.SimpleNamespace(description="build a service")
    cp = types.SimpleNamespace(phase_count=0)
    await plan.run(engine, req, detail, "rid", cp, str(root), {}, True)
    rows = await db.read("SELECT content_text FROM artifacts WHERE run_id=? AND kind='devplan_tasks'", ("rid",))
    return json.loads(rows[0]["content_text"])


@pytest.mark.asyncio
async def test_devplan_tasks_contract_strict(tmp_path):
    provider = _devplan_markdown() + "\n```json\n" + json.dumps([
        {
            "task_id": "T-010",
            "title": "Build API",
            "acceptance_criteria": "tests pass",
            "files_allowed": ["core/nexussy/api/server.py"],
            "depends_on": [],
            "owner": "A",
            "estimated_tokens": 1200,
        }
    ]) + "\n```"
    tasks = await _run_plan(tmp_path, provider, "strict")
    assert tasks == [{
        "task_id": "T-010",
        "title": "Build API",
        "acceptance_criteria": "tests pass",
        "files_allowed": ["core/nexussy/api/server.py"],
        "depends_on": [],
        "owner": "A",
        "estimated_tokens": 1200,
    }]


@pytest.mark.asyncio
async def test_devplan_tasks_repair_missing(tmp_path):
    provider = _devplan_markdown() + "\n```json\n" + json.dumps([
        {"title": "Build API", "acceptance_criteria": "tests pass"}
    ]) + "\n```"
    tasks = await _run_plan(tmp_path, provider, "repair")
    assert tasks[0]["task_id"] == "T-auto-1"
    assert tasks[0]["owner"] == "unknown"
    assert tasks[0]["depends_on"] == []
    assert tasks[0]["files_allowed"] == ["*"]


def test_devplan_fallback_markdown():
    from nexussy.pipeline.stages.develop import _slice_devplan_tasks

    tasks = _slice_devplan_tasks(_devplan_markdown())
    assert tasks[0]["task_id"] == "T-001"
    assert tasks[0]["title"] == "Build API"
    assert tasks[0]["acceptance_criteria"] == "tests pass"
    assert tasks[0]["files_allowed"] == ["core/nexussy/api/server.py"]
