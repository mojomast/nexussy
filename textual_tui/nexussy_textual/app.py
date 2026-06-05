from __future__ import annotations

import asyncio
from dataclasses import replace

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input
from textual.events import Key

from .actions import ActionDispatcher
from .client import CoreClient, CoreClientError
from .models import AppState, STAGES, TranscriptItem, create_state
from .screens import CommandPaletteScreen, HelpScreen, RoutingScreen, SimpleTableScreen
from .state import apply_event, apply_providers, edit_stage_route, stage_artifacts, stage_workers, switch_profile
from .widgets import Composer, GateCard, HeaderBar, InspectorPanel, InterviewPanel, PipelineSidebar, StageControlPanel, StatusBar, TranscriptPanel


class NexussyTextualApp(App[None]):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands", priority=True),
        Binding("?", "help", "Help"),
        Binding("escape", "escape", "Back", priority=True),
        Binding("up,k", "stage_prev", "Prev stage"),
        Binding("down,j", "stage_next", "Next stage"),
        Binding("c", "stage_chat", "Stage chat"),
        Binding("a", "inspector('artifacts')", "Artifacts"),
        Binding("w", "inspector('workers')", "Workers"),
        Binding("l", "inspector('logs')", "Logs"),
        Binding("r", "routing", "Routing"),
        Binding("d", "inspector('diagnostics')", "Diagnostics"),
        Binding("p", "pause", "Pause"),
        Binding("u", "resume", "Resume"),
        Binding("x", "cancel", "Cancel"),
        Binding("s", "skip", "Skip"),
        Binding("y", "advance_gate", "Advance gate"),
        Binding("n", "stay_paused", "Stay paused"),
    ]

    def __init__(self, client: CoreClient | None = None, state: AppState | None = None) -> None:
        super().__init__()
        self.client = client or CoreClient()
        self.dispatcher = ActionDispatcher(self.client)
        self.state: AppState = state or create_state()
        self.inspector_mode = "artifacts"
        self._stream_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        with Horizontal(id="body"):
            yield PipelineSidebar(id="pipeline-sidebar")
            with Vertical(id="main-pane"):
                yield GateCard(id="gate-card")
                yield InterviewPanel(id="interview-panel")
                yield TranscriptPanel(id="transcript-panel")
                yield StageControlPanel(id="stage-controls")
            yield InspectorPanel(id="inspector-panel")
        yield Composer(id="composer-box")
        yield StatusBar(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_from_core()
        self.render_all()
        self.focus_composer()

    async def on_unmount(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
        await self.client.close()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.action_escape()
            event.stop()
            event.prevent_default()
        elif event.key in {"up", "down"} and self.focused and self.focused.id == "composer":
            self.cycle_history(-1 if event.key == "up" else 1)
            event.stop()
            event.prevent_default()
        elif event.key == "enter" and self.focused and self.focused.id == "inspector-table" and self.inspector_mode == "routing":
            self.cycle_selected_stage_model()
            event.stop()
            event.prevent_default()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.focused and self.focused.id == "composer":
            blocked = {
                "stage_prev",
                "stage_next",
                "stage_chat",
                "inspector",
                "routing",
                "pause",
                "resume",
                "cancel",
                "skip",
                "advance_gate",
                "stay_paused",
            }
            if action in blocked:
                return False
        return True

    async def refresh_from_core(self) -> None:
        try:
            health = await self.client.health()
            secrets = await self.client.secrets()
            self.state = apply_providers(replace(self.state, connection="connected"), secrets, health if isinstance(health, dict) else None)
        except Exception as exc:
            self.state = replace(self.state, connection="error", status_message=f"Core unavailable: {exc}")

    def render_all(self) -> None:
        self.query_one(HeaderBar).render_state(self.state)
        self.query_one(PipelineSidebar).render_state(self.state)
        self.query_one(GateCard).render_state(self.state)
        self.query_one(InterviewPanel).render_state(self.state)
        self.query_one(TranscriptPanel).render_state(self.state)
        self.query_one(StageControlPanel).render_state(self.state)
        self.query_one(InspectorPanel).render_state(self.state, self.inspector_mode)
        self.query_one(Composer).render_state(self.state)
        self.query_one(StatusBar).render_state(self.state)

    def focus_composer(self) -> None:
        self.set_focus(self.query_one("#composer", Input))

    def cycle_history(self, direction: int) -> None:
        if not self.state.command_history:
            return
        current = self.state.history_index
        if current is None:
            current = len(self.state.command_history) if direction < 0 else -1
        index = max(0, min(len(self.state.command_history) - 1, current + direction))
        self.state = replace(self.state, history_index=index)
        self.query_one("#composer", Input).value = self.state.command_history[index]

    def cycle_selected_stage_model(self) -> None:
        options = [option for option in self.state.model_options if option.configured]
        if not options:
            self.state = replace(self.state, status_message="No configured model options")
            self.render_all()
            return
        stage = self.state.selected_stage
        current = self.state.routing[stage].primary
        index = next((i for i, option in enumerate(options) if option == current), -1)
        self.state = edit_stage_route(self.state, stage, "primary", options[(index + 1) % len(options)])
        self.render_all()

    def reduce_event(self, env: dict) -> None:
        self.state = apply_event(self.state, env)
        self.render_all()

    async def watch_run(self, run_id: str) -> None:
        async for event in self.client.stream_run(run_id):
            self.reduce_event(event)

    def on_pipeline_sidebar_stage_selected(self, event: PipelineSidebar.StageSelected) -> None:
        self.state = self.dispatcher.open_stage_chat(replace(self.state, selected_stage=event.stage), event.stage)
        self.render_all()

    async def on_stage_control_panel_stage_action(self, event: StageControlPanel.StageAction) -> None:
        if event.action == "pause":
            self.state = await self.dispatcher.pause_stage(self.state, event.stage)
        elif event.action == "resume":
            self.state = await self.dispatcher.resume_stage(self.state, event.stage)
        elif event.action == "cancel":
            self.state = replace(self.state, pending_control=("cancel", event.stage), status_message="Are you sure? This cannot be undone. Press y/n.")
            self.focus_composer()
        elif event.action == "skip":
            self.state = replace(self.state, pending_control=("skip", event.stage), status_message=f"Enter skip reason for {event.stage}")
            self.focus_composer()
        elif event.action == "advance-gate":
            self.state = await self.dispatcher.advance_gate(self.state)
        elif event.action == "chat":
            self.state = self.dispatcher.open_stage_chat(self.state, event.stage)
            self.focus_composer()
        elif event.action in {"artifacts", "workers", "routing"}:
            self.inspector_mode = event.action
        self.render_all()

    async def on_gate_card_gate_action(self, event: GateCard.GateAction) -> None:
        gate = self.state.pending_gate
        if event.action == "advance":
            self.state = await self.dispatcher.advance_gate(self.state)
        elif event.action == "stay":
            self.state = await self.dispatcher.stay_paused(self.state)
        elif event.action == "gate-chat" and gate:
            self.state = self.dispatcher.open_stage_chat(self.state, gate.completed_stage)
            self.focus_composer()
        elif event.action == "gate-artifacts":
            self.inspector_mode = "artifacts"
        elif event.action == "gate-workers":
            self.inspector_mode = "workers"
        self.render_all()

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        await self.submit_composer_text(event.text)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "composer":
            return
        text = event.value.strip()
        if not text and self.state.interview.suggested_answer:
            text = "__accept_suggestion__"
        event.input.value = ""
        await self.submit_composer_text(text)

    async def submit_composer_text(self, text: str) -> None:
        if not text.strip():
            self.state = replace(self.state, status_message="Type a message, then press Enter")
            self.render_all()
            self.focus_composer()
            return
        display_text = self.state.interview.suggested_answer if text == "__accept_suggestion__" else text
        scope = self.state.stage_chat_scope or (self.state.pending_gate.completed_stage if self.state.pending_gate else None)
        self.state = replace(
            self.state,
            transcript=(
                *self.state.transcript,
                TranscriptItem(f"composer-{len(self.state.transcript) + 1}", scope, "user", display_text),
            ),
            status_message="Submitting...",
        )
        self.render_all()
        if text.strip() and text != "__accept_suggestion__":
            self.state = replace(self.state, command_history=(*self.state.command_history, text), history_index=None)
        try:
            self.state = await self.dispatcher.send_chat(self.state, text)
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            if isinstance(exc, CoreClientError) or "connection" in message.lower() or "connect" in message.lower():
                message = "Core is not reachable. Start it with ./nexussy.sh start, then try again."
            self.state = replace(
                self.state,
                connection="error",
                status_message=message,
                transcript=(
                    *self.state.transcript,
                    TranscriptItem(f"composer-error-{len(self.state.transcript) + 1}", None, "system", message),
                ),
            )
        self.render_all()
        self.focus_composer()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_command_palette(self) -> None:
        self.push_screen(CommandPaletteScreen())

    def action_escape(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
            self.focus_composer()
            return
        if self.state.stage_chat_scope:
            self.state = self.dispatcher.close_stage_chat(self.state)
            self.render_all()
            self.focus_composer()
        else:
            self.focus_composer()

    def action_stage_prev(self) -> None:
        index = max(0, STAGES.index(self.state.selected_stage) - 1)
        self.state = replace(self.state, selected_stage=STAGES[index])
        self.render_all()

    def action_stage_next(self) -> None:
        index = min(len(STAGES) - 1, STAGES.index(self.state.selected_stage) + 1)
        self.state = replace(self.state, selected_stage=STAGES[index])
        self.render_all()

    def action_stage_chat(self) -> None:
        self.state = self.dispatcher.open_stage_chat(self.state, self.state.selected_stage)
        self.render_all()
        self.focus_composer()

    def action_inspector(self, mode: str) -> None:
        self.inspector_mode = "artifacts" if mode == "logs" else mode
        self.render_all()
        if mode in {"artifacts", "workers", "routing", "diagnostics"}:
            self.set_focus(self.query_one("#inspector-table", DataTable))

    def action_routing(self) -> None:
        self.push_screen(RoutingScreen(self.state))

    async def action_pause(self) -> None:
        self.state = await self.dispatcher.pause_stage(self.state, self.state.selected_stage)
        self.render_all()

    async def action_resume(self) -> None:
        self.state = await self.dispatcher.resume_stage(self.state, self.state.selected_stage)
        self.render_all()

    async def action_cancel(self) -> None:
        self.state = replace(self.state, pending_control=("cancel", self.state.selected_stage), status_message="Are you sure? This cannot be undone. Press y/n.")
        self.render_all()
        self.focus_composer()

    async def action_skip(self) -> None:
        self.state = replace(self.state, pending_control=("skip", self.state.selected_stage), status_message=f"Enter skip reason for {self.state.selected_stage}")
        self.render_all()
        self.focus_composer()

    async def action_advance_gate(self) -> None:
        self.state = await self.dispatcher.advance_gate(self.state)
        self.render_all()

    async def action_stay_paused(self) -> None:
        self.state = await self.dispatcher.stay_paused(self.state)
        self.render_all()

    def action_switch_profile(self, profile: str) -> None:
        self.state = switch_profile(self.state, profile)
        self.render_all()

    def action_open_workers_screen(self) -> None:
        rows = [(w.worker_id, w.role, w.stage or "-", w.status, w.task) for w in stage_workers(self.state, self.state.selected_stage)]
        self.push_screen(SimpleTableScreen("Workers", ("worker", "role", "stage", "status", "task"), rows))

    def action_open_artifacts_screen(self) -> None:
        rows = [(a.kind, a.stage or "-", a.path, a.updated_at) for a in stage_artifacts(self.state, self.state.selected_stage)]
        self.push_screen(SimpleTableScreen("Artifacts", ("kind", "stage", "path", "updated"), rows))


def main() -> None:
    NexussyTextualApp().run()


if __name__ == "__main__":
    main()
