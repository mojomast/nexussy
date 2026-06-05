import asyncio

import pytest

from nexussy_textual.app import NexussyTextualApp
from nexussy_textual.models import InterviewState, PendingGate, create_state


class FakeClient:
    def __init__(self):
        self.calls = []

    async def close(self):
        self.calls.append(("close",))

    async def health(self):
        return {"ok": True, "providers_configured": ["mock"]}

    async def secrets(self):
        return [{"name": "mock", "configured": True}]

    async def pause(self, run_id, reason="user"):
        self.calls.append(("pause", run_id, reason))
        return {"ok": True}

    async def resume(self, run_id):
        self.calls.append(("resume", run_id))
        return {"ok": True}

    async def cancel(self, run_id, reason="user"):
        self.calls.append(("cancel", run_id, reason))
        return {"ok": True}

    async def skip(self, run_id, stage, reason="user"):
        self.calls.append(("skip", run_id, stage, reason))
        return {"ok": True}

    async def status(self, run_id):
        return {"run": {"run_id": run_id, "session_id": "sess-1"}, "stages": [], "workers": [], "paused": False}

    async def inject(self, run_id, message, stage=None, worker_id=None):
        self.calls.append(("inject", run_id, message, stage, worker_id))
        return {"ok": True}

    async def interview_answer(self, session_id, answers):
        self.calls.append(("interview_answer", session_id, answers))
        return {"ok": True}

    async def start_pipeline(self, body):
        self.calls.append(("start_pipeline", body))
        return {"run_id": "run-new", "session_id": "sess-new"}


class DownClient(FakeClient):
    async def start_pipeline(self, body):
        raise OSError("All connection attempts failed")


class FakeSSEClient(FakeClient):
    async def start_pipeline(self, body):
        self.calls.append(("start_pipeline", body))
        return {"run_id": "run-sse", "session_id": "sess-sse"}

    async def stream_run(self, run_id):
        for event in [
            {"type": "run_started", "run_id": "run-sse", "payload": {"current_stage": "interview"}},
            {"type": "content_delta", "run_id": "run-sse", "payload": {"stage": "interview", "role": "assistant", "delta": "Hello from SSE"}},
            {"type": "stage_transition", "run_id": "run-sse", "payload": {"from_stage": "interview", "to_stage": "design", "from_status": "passed"}},
            {"type": "done", "run_id": "run-sse", "payload": {"final_status": "passed"}},
        ]:
            yield event


@pytest.mark.asyncio
async def test_keyboard_navigation_and_focus_return():
    state = create_state().__class__(**{**create_state().__dict__, "run_id": "run-1", "session_id": "sess-1"})
    app = NexussyTextualApp(client=FakeClient(), state=state)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one("#stage-list").focus()
        await pilot.press("j")
        assert app.state.selected_stage == "design"
        await pilot.press("c")
        assert app.state.stage_chat_scope == "design"
        await pilot.press("escape")
        assert app.state.stage_chat_scope is None
        assert app.focused.id == "composer"


@pytest.mark.asyncio
async def test_gate_keyboard_actions_and_stage_chat_injection():
    base = create_state()
    state = base.__class__(**{**base.__dict__, "run_id": "run-1", "session_id": "sess-1", "pending_gate": PendingGate("design", "validate", "ready"), "paused": True})
    client = FakeClient()
    app = NexussyTextualApp(client=client, state=state)
    async with app.run_test(size=(120, 32)) as pilot:
        app.query_one("#stage-list").focus()
        await pilot.press("n")
        assert app.state.pending_gate is not None
        await pilot.press("c")
        assert app.state.stage_chat_scope == "interview"
        app.state = app.state.__class__(**{**app.state.__dict__, "stage_chat_scope": "design"})
        await pilot.click("#composer")
        await pilot.press("p", "l", "e", "a", "s", "e", "space", "r", "e", "v", "i", "s", "e", "enter")
        assert any(call[0] == "inject" and call[3] == "design" for call in client.calls)
        app.state = app.state.__class__(**{**app.state.__dict__, "pending_gate": PendingGate("design", "validate", "ready")})
        app.query_one("#stage-list").focus()
        await pilot.press("y")
        assert app.state.pending_gate is None


@pytest.mark.asyncio
async def test_help_overlay_closes_with_escape():
    app = NexussyTextualApp(client=FakeClient(), state=create_state())
    async with app.run_test(size=(80, 24)) as pilot:
        app.query_one("#stage-list").focus()
        await pilot.press("?")
        assert len(app.screen_stack) > 1
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_command_palette_opens_and_closes():
    app = NexussyTextualApp(client=FakeClient(), state=create_state())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+p")
        assert len(app.screen_stack) > 1
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_composer_starts_run_and_keeps_history():
    client = FakeClient()
    app = NexussyTextualApp(client=client, state=create_state())
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.focused.id == "composer"
        await pilot.press("b", "u", "i", "l", "d", "space", "a", "space", "t", "u", "i", "enter")
        assert app.state.run_id == "run-new"
        assert any(call[0] == "start_pipeline" for call in client.calls)
        await pilot.press("up")
        assert app.query_one("#composer").value == "build a tui"


@pytest.mark.asyncio
async def test_typing_in_composer_is_not_eaten_by_shortcuts():
    app = NexussyTextualApp(client=FakeClient(), state=create_state())
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.focused.id == "composer"
        await pilot.press("p", "c", "r", "s", "n", "y")
        assert app.query_one("#composer").value == "pcrsny"
        assert app.state.stage_chat_scope is None
        assert app.state.pending_control is None


@pytest.mark.asyncio
async def test_enter_submit_adds_visible_transcript_feedback():
    client = FakeClient()
    app = NexussyTextualApp(client=client, state=create_state())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("h", "e", "l", "l", "o", "enter")
        assert app.query_one("#composer").value == ""
        assert any(item.role == "user" and item.text == "hello" for item in app.state.transcript)
        assert any(call[0] == "start_pipeline" for call in client.calls)


@pytest.mark.asyncio
async def test_interview_prefills_suggestion_and_submits_answer():
    base = create_state()
    state = base.__class__(**{**base.__dict__, "session_id": "sess-1", "interview": InterviewState(question_id="q2", question="Platform?", suggested_answer="web", answered=1, total_hint=5)})
    client = FakeClient()
    app = NexussyTextualApp(client=client, state=state)
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.query_one("#composer").value == "web"
        await pilot.press("enter")
        assert any(call[0] == "interview_answer" and call[2] == {"q2": "web"} for call in client.calls)
        assert app.state.interview.waiting is True


@pytest.mark.asyncio
async def test_gate_yes_from_composer_resumes_and_clears_gate():
    base = create_state()
    state = base.__class__(**{**base.__dict__, "run_id": "run-1", "pending_gate": PendingGate("design", "validate", "ready"), "paused": True})
    client = FakeClient()
    app = NexussyTextualApp(client=client, state=state)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("y", "e", "s", "enter")
        assert app.state.pending_gate is None
        assert any(call[0] == "resume" for call in client.calls)


@pytest.mark.asyncio
async def test_submit_when_core_down_shows_status_not_traceback():
    app = NexussyTextualApp(client=DownClient(), state=create_state())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("h", "i", "enter")
        assert "Core is not reachable" in app.state.status_message
        assert app.focused.id == "composer"


@pytest.mark.asyncio
async def test_routing_tab_enter_edits_selected_stage_model():
    app = NexussyTextualApp(client=FakeClient(), state=create_state())
    async with app.run_test(size=(100, 30)) as pilot:
        before = app.state.routing["interview"].primary
        app.action_inspector("routing")
        await pilot.press("enter")
        assert app.state.routing["interview"].primary != before


@pytest.mark.asyncio
async def test_sse_events_update_transcript_and_sidebar():
    client = FakeSSEClient()
    app = NexussyTextualApp(client=client, state=create_state())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b", "u", "i", "l", "d", "enter")
        await asyncio.sleep(0.1)
        assert any(item.text == "Hello from SSE" for item in app.state.transcript)
        assert app.state.stages["interview"].status == "passed"
        assert app.state.stages["design"].status == "running"
        assert app.state.final_status == "passed"
