import asyncio, contextlib, json

import httpx
import pytest

from nexussy.api import server
from nexussy.api.server import app
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine
from nexussy.providers import ProviderResult


QUESTIONS = [
    {"id":"q_name","question":"What is the name of your project?"},
    {"id":"q_lang","question":"What programming language(s) will you use?"},
    {"id":"q_desc","question":"Describe what your project does in 1-2 sentences."},
    {"id":"q_type","question":"What type of project is this? (API, Web App, CLI, Game, etc.)"},
]


async def reset_core(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    await server.db.init()


def fake_complete_factory(prompts):
    async def fake_complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        prompts.append((stage, prompt))
        usage={"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model}
        if "Generate a JSON array" in prompt:
            return ProviderResult(json.dumps(QUESTIONS), usage)
        if "Answer these interview questions" in prompt:
            return ProviderResult(json.dumps({
                "q_name":"HabitTrack",
                "q_lang":"Python",
                "q_desc":"A REST API for tracking habits from the project description.",
                "q_type":"API",
            }), usage)
        if stage == "design":
            return ProviderResult("# Goals\nDesign HabitTrack.\n# Architecture\nAPI from interview.\n# Dependencies\nPython.\n# Risks\nNone.\n# Test Strategy\nPytest.", usage)
        return ProviderResult(f"# {stage}\n{prompt}", usage)
    return fake_complete


async def client():
    transport=httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def start_and_wait(c, *, stop_after_stage="interview", auto=True):
    r=await c.post("/pipeline/start", json={"project_name":"HabitTrack","description":"Build a Python REST API for tracking habits with SQLite tests","auto_approve_interview":auto,"stop_after_stage":stop_after_stage,"metadata":{"mock_provider":True}})
    assert r.status_code == 200, r.text
    body=r.json()
    for _ in range(100):
        ev=(await c.get("/events", params={"run_id":body["run_id"]})).json()
        if ev and ev[-1]["type"] == "done": return body, ev
        await asyncio.sleep(.02)
    raise AssertionError("pipeline did not finish")


@pytest.mark.asyncio
async def test_interview_questions_generated(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory([]))
    async with await client() as c:
        body, _ = await start_and_wait(c)
        artifact=json.loads((await c.get("/pipeline/artifacts/interview", params={"session_id":body["session_id"]})).json()["content_text"])
    assert len(artifact["questions"]) >= 4
    assert all(q["question"] and q["question"] != "Use defaults?" for q in artifact["questions"])
    assert {q["source"] for q in artifact["questions"]} == {"auto"}


@pytest.mark.asyncio
async def test_interview_auto_answers_use_description(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory([]))
    async with await client() as c:
        body, _ = await start_and_wait(c)
        artifact=json.loads((await c.get("/pipeline/artifacts/interview", params={"session_id":body["session_id"]})).json()["content_text"])
    answers=[q["answer"] for q in artifact["questions"]]
    assert all(a and a not in {"True", "False"} for a in answers)
    assert "Python" in answers and any("habit" in a.lower() for a in answers)


@pytest.mark.asyncio
async def test_interview_blocks_pipeline_when_manual(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory([]))
    async with await client() as c:
        r=await c.post("/pipeline/start", json={"project_name":"Manual","description":"Build a TypeScript web app","auto_approve_interview":False,"stop_after_stage":"design","metadata":{"mock_provider":True}})
        assert r.status_code == 200, r.text
        body=r.json()
        for _ in range(100):
            status=(await c.get("/pipeline/status", params={"run_id":body["run_id"]})).json()
            events=(await c.get("/events", params={"run_id":body["run_id"]})).json()
            if status["run"]["status"] == "paused": break
            await asyncio.sleep(.02)
        assert status["run"]["status"] == "paused"
        assert not any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "design" for e in events)
        pending=json.loads((await c.get("/pipeline/artifacts/interview", params={"session_id":body["session_id"]})).json()["content_text"])
        answers={q["question_id"]: f"user answer for {q['question_id']}" for q in pending["questions"]}
        posted=await c.post(f"/pipeline/{body['session_id']}/interview/answer", json={"answers":answers})
        assert posted.status_code == 200, posted.text
        for _ in range(100):
            events=(await c.get("/events", params={"run_id":body["run_id"]})).json()
            if any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "design" for e in events): break
            await asyncio.sleep(.02)
        assert any(e["type"] == "stage_transition" and e["payload"].get("to_stage") == "design" for e in events)


@pytest.mark.asyncio
async def test_cancel_waiting_interview_cleans_waiter_state(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory([]))
    async with await client() as c:
        r=await c.post("/pipeline/start", json={"project_name":"CancelManual","description":"Build a TypeScript web app","auto_approve_interview":False,"metadata":{"mock_provider":True}})
        assert r.status_code == 200, r.text
        body=r.json()
        for _ in range(100):
            status=(await c.get("/pipeline/status", params={"run_id":body["run_id"]})).json()
            if status["run"]["status"] == "paused": break
            await asyncio.sleep(.02)
        assert body["session_id"] in server.engine.interview_waiters
        assert body["session_id"] in server.engine.interview_questions
        cancelled=await c.post("/pipeline/cancel", json={"run_id":body["run_id"],"reason":"test cancel"})
        assert cancelled.status_code == 200, cancelled.text
        task=server.engine.tasks[body["run_id"]]
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert body["session_id"] not in server.engine.interview_waiters
        assert body["session_id"] not in server.engine.interview_questions


@pytest.mark.asyncio
async def test_interview_artifact_in_design_prompt(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    prompts=[]
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory(prompts))
    async with await client() as c:
        await start_and_wait(c, stop_after_stage="design")
    design_prompts=[p for stage, p in prompts if stage == "design"]
    assert design_prompts
    assert "Project Requirements (from Interview)" in design_prompts[-1]
    assert "HabitTrack" in design_prompts[-1]
    assert "tracking habits" in design_prompts[-1]


@pytest.mark.asyncio
async def test_interview_provider_retry_and_question_checkpoint(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    attempts={"questions":0}
    async def flaky_complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        if "Generate a JSON array" in prompt:
            attempts["questions"] += 1
            if attempts["questions"] == 1:
                raise RuntimeError("transient provider failure")
            return ProviderResult(json.dumps(QUESTIONS), {"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model})
        return await fake_complete_factory([])(stage, prompt, model, allow_mock=allow_mock, timeout_s=timeout_s, _env=_env, db=db)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", flaky_complete)
    async with await client() as c:
        body, events = await start_and_wait(c)
    assert attempts["questions"] == 2
    checkpoints=[e for e in events if e["type"] == "checkpoint_saved"]
    assert any(e["payload"]["path"] == ".nexussy/checkpoints/interview-questions.json" for e in checkpoints)


@pytest.mark.asyncio
async def test_interview_autoskip(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory([]))
    async with await client() as c:
        r=await c.post("/pipeline/start", json={"project_name":"HabitTrack","description":"Build a Python REST API for tracking habits with SQLite tests","auto_approve_interview":False,"stop_after_stage":"interview","metadata":{"mock_provider":True,"skip_interview":"true"}})
        assert r.status_code == 200, r.text
        body=r.json()
        for _ in range(200):
            ev=(await c.get("/events", params={"run_id":body["run_id"]})).json()
            if ev and ev[-1]["type"] == "done": break
            status=(await c.get("/pipeline/status", params={"run_id":body["run_id"]})).json()
            assert status["run"]["status"] != "paused", "skip_interview should not pause"
            await asyncio.sleep(.02)
        else:
            raise AssertionError("pipeline did not finish")
        assert not any(e["type"] == "pause_state_changed" and e["payload"].get("paused") for e in ev)
        artifact=json.loads((await c.get("/pipeline/artifacts/interview", params={"session_id":body["session_id"]})).json()["content_text"])
    assert len(artifact["questions"]) >= 4
    assert {q["source"] for q in artifact["questions"]} == {"auto"}


@pytest.mark.asyncio
async def test_interview_replay(tmp_path, monkeypatch):
    await reset_core(tmp_path, monkeypatch)
    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete_factory([]))
    async with await client() as c:
        body, _ = await start_and_wait(c, stop_after_stage="develop")
        first=(await c.get("/pipeline/artifacts/interview", params={"session_id":body["session_id"]})).json()["content_text"]
        replay=(await c.get("/events", params={"run_id":body["run_id"],"after_sequence":0})).json()
        second=(await c.get("/pipeline/artifacts/interview", params={"session_id":body["session_id"]})).json()["content_text"]
    assert replay and replay[0]["type"] == "run_started"
    assert json.loads(first) == json.loads(second)
