import asyncio
import json
import subprocess

import httpx
import pytest

from nexussy.api import server
from nexussy.api.server import app
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine
from nexussy.providers import ProviderResult
from nexussy.swarm.project_graph import graph_cache_path


QUESTIONS = [
    {"id": "q_name", "question": "What is the project name?"},
    {"id": "q_lang", "question": "What language is used?"},
    {"id": "q_desc", "question": "What should it do?"},
    {"id": "q_type", "question": "What type of app is it?"},
]


async def reset_core(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    await server.db.init()


def fake_complete(prompts):
    async def complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        prompts.append(prompt)
        usage = {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0, "provider": "mock", "model": model}
        if "Generate a JSON array" in prompt:
            return ProviderResult(json.dumps(QUESTIONS), usage)
        return ProviderResult(json.dumps({q["id"]: "answer" for q in QUESTIONS}), usage)

    return complete


def make_git_repo(path):
    path.mkdir()
    (path / "README.md").write_text("# Existing project\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("import json\nprint('hello')\n", encoding="utf-8")
    (path / "large.txt").write_text("raw dump should not appear\n" * 20000, encoding="utf-8")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


async def start_interview(existing_repo_path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/pipeline/start",
            json={
                "project_name": "GraphApp",
                "description": "Build from the existing Python repo",
                "existing_repo_path": str(existing_repo_path),
                "auto_approve_interview": True,
                "stop_after_stage": "interview",
                "metadata": {"mock_provider": True},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        for _ in range(100):
            events = (await client.get("/events", params={"run_id": body["run_id"]})).json()
            if events and events[-1]["type"] == "done":
                return body
            await asyncio.sleep(0.02)
    raise AssertionError("pipeline did not finish")


@pytest.mark.asyncio
async def test_interview_prompts_include_compressed_graph_context(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    make_git_repo(repo)
    prompts = []
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete(prompts))

    body = await start_interview(repo)
    session_root = tmp_path / "projects" / "graphapp" / "main"

    assert graph_cache_path(session_root).exists()
    assert len(prompts) == 2
    assert all("Project graph context" in prompt for prompt in prompts)
    assert all("README.md" in prompt and "src=source_root [inferred]" in prompt for prompt in prompts)
    assert all("raw dump should not appear" not in prompt for prompt in prompts)
    assert body["session_id"]


@pytest.mark.asyncio
async def test_interview_graph_failure_falls_back_to_minimal_context(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    make_git_repo(repo)
    prompts = []
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete(prompts))

    def fail_graph(root):
        raise RuntimeError("boom")

    monkeypatch.setattr("nexussy.swarm.project_graph.build_or_load_project_graph", fail_graph)

    await start_interview(repo)

    assert prompts
    assert all("Project graph context unavailable" in prompt for prompt in prompts)
    assert all("raw dump should not appear" not in prompt for prompt in prompts)
