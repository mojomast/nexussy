from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Label, ListItem, ListView, RichLog, Static

from .models import AppState, STAGE_LABELS, STAGES, StageName
from .state import filtered_transcript, stage_artifacts, stage_workers


class HeaderBar(Static):
    def render_state(self, state: AppState) -> None:
        health = ", ".join(f"{k}:{v}" for k, v in sorted(state.diagnostics.provider_health.items())) or "unknown"
        self.update(f"nexussy | project {state.project_name} | run {state.run_id or '-'} | session {state.session_id or '-'} | profile {state.profile} | providers {health}")


class PipelineSidebar(Vertical):
    class StageSelected(Message):
        def __init__(self, stage: StageName) -> None:
            self.stage = stage
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("Pipeline", classes="panel-title")
        yield ListView(*[ListItem(Label("", id=f"stage-label-{stage}")) for stage in STAGES], id="stage-list")

    def on_mount(self) -> None:
        self.query_one(ListView).can_focus = True

    def render_state(self, state: AppState) -> None:
        listing = self.query_one(ListView)
        icons = {"running": "●", "passed": "✓", "failed": "✗", "paused": "Ⅱ", "pending": "○", "retrying": "↻", "skipped": "○", "blocked": "⏸"}
        for index, stage in enumerate(STAGES, start=1):
            row = state.stages[stage]
            route = row.routing
            model = route.primary.label if route else "-"
            fallback = route.fallback.label if route else "-"
            flags = []
            if state.active_stage == stage:
                flags.append("ACTIVE")
            if state.pending_gate and state.pending_gate.next_stage == stage:
                flags.append("BLOCKED")
            if row.gated:
                flags.append("gated")
            if row.paused:
                flags.append("paused")
            if row.retrying:
                flags.append("retrying")
            prefix = "⏸" if state.pending_gate and state.pending_gate.next_stage == stage else icons.get(row.status, "○")
            cursor = "▶" if state.active_stage == stage else " "
            text = f"{cursor} {prefix} {index}. {row.label}\n   {row.status} {row.activity} workers:{row.active_workers}\n   model {model}\n   fallback {fallback}\n   {' '.join(flags) or 'ready'}"
            self.query_one(f"#stage-label-{stage}", Label).update(text)
        listing.index = STAGES.index(state.selected_stage)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is not None:
            self.post_message(self.StageSelected(STAGES[event.list_view.index]))


class StageControlPanel(Vertical):
    class StageAction(Message):
        def __init__(self, action: str, stage: StageName) -> None:
            self.action = action
            self.stage = stage
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("Stage Controls", classes="panel-title")
        with Horizontal(classes="button-row"):
            yield Button("Pause [p]", id="pause")
            yield Button("Resume [u]", id="resume")
            yield Button("Cancel [x]", id="cancel")
            yield Button("Skip [s]", id="skip")
            yield Button("Advance Gate [y]", id="advance-gate")
        with Horizontal(classes="button-row"):
            yield Button("Stage Chat [c]", id="chat")
            yield Button("Artifacts [a]", id="artifacts")
            yield Button("Workers [w]", id="workers")
            yield Button("Routing [r]", id="routing")
        yield Static(id="stage-detail")

    def render_state(self, state: AppState) -> None:
        stage = state.selected_stage
        row = state.stages[stage]
        route = row.routing
        self.query_one("#pause", Button).disabled = state.paused or row.status not in {"running", "retrying"}
        self.query_one("#resume", Button).disabled = not state.paused and not state.pending_gate
        self.query_one("#advance-gate", Button).display = bool(state.pending_gate and state.pending_gate.completed_stage == stage)
        self.query_one("#stage-detail", Static).update(
            f"{row.label}: {row.status}\nActivity: {row.activity}\nPrimary: {route.primary.label if route else '-'}\nFallback: {route.fallback.label if route else '-'}\nWorker group: {route.worker_group if route else '-'}\nArtifacts: {len(stage_artifacts(state, stage))} | Workers: {len(stage_workers(state, stage))}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app_state = self.app.state
        action = str(event.button.id)
        self.post_message(self.StageAction(action, app_state.selected_stage))


class GateCard(Vertical):
    class GateAction(Message):
        def __init__(self, action: str) -> None:
            self.action = action
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("Stage Gate", classes="panel-title")
        yield Static("No gate pending", id="gate-summary")
        with Horizontal(classes="button-row"):
            yield Button("Advance [y]", id="advance")
            yield Button("Stay Paused [n]", id="stay")
            yield Button("Open Stage Chat", id="gate-chat")
            yield Button("Review Artifacts", id="gate-artifacts")
            yield Button("View Workers", id="gate-workers")

    def render_state(self, state: AppState) -> None:
        gate = state.pending_gate
        if not gate:
            self.display = False
            return
        self.display = True
        artifacts = ", ".join(gate.artifacts[:3]) or "no artifacts listed yet"
        next_step = STAGE_LABELS[gate.next_stage] if gate.next_stage else "finish"
        self.query_one("#gate-summary", Static).update(f"Stage complete: {STAGE_LABELS[gate.completed_stage]} -> next: {next_step}\nSummary: {gate.summary}\nDesign artifacts: {artifacts}\nReview: /artifacts  /plan  /workers\nType yes to advance, or chat here to iterate first.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.post_message(self.GateAction(str(event.button.id)))


class TranscriptPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Transcript", classes="panel-title")
        yield RichLog(id="transcript-log", wrap=True, highlight=True)

    def render_state(self, state: AppState) -> None:
        log = self.query_one(RichLog)
        log.clear()
        title = f"Viewing stage: {STAGE_LABELS[state.stage_chat_scope]}" if state.stage_chat_scope else "Global transcript"
        log.write(title)
        for item in filtered_transcript(state)[-80:]:
            scope = f"[{STAGE_LABELS[item.stage]}] " if item.stage else ""
            worker = f" {item.worker_id}" if item.worker_id else ""
            log.write(f"{scope}{item.role}{worker}: {item.text}")


class InterviewPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Interview", classes="panel-title")
        yield Static("No active interview question", id="interview-card")

    def render_state(self, state: AppState) -> None:
        interview = state.interview
        if not interview.question_id:
            self.display = False
            return
        self.display = True
        progress = f"Question {interview.answered + 1}" + (f" of {interview.total_hint}" if interview.total_hint else "")
        suggestion = f"\nSuggested answer: {interview.suggested_answer}\nEnter accepts suggestion." if interview.suggested_answer else ""
        waiting = "\nWaiting for next question..." if interview.waiting else ""
        self.query_one("#interview-card", Static).update(f"┌─ Interview: {progress} ─────────────────────────\n│ {interview.question}{suggestion}\n└─ Press Enter to accept suggestion, or type your answer ─{waiting}")


class InspectorPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Inspector", classes="panel-title")
        yield DataTable(id="inspector-table")

    def render_state(self, state: AppState, mode: str = "artifacts") -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        stage = state.selected_stage
        if mode == "workers":
            table.add_columns("worker", "role", "stage", "status", "task")
            for worker in stage_workers(state, stage):
                table.add_row(worker.worker_id, worker.role, worker.stage or "-", worker.status, worker.task)
        elif mode == "routing":
            route = state.routing[stage]
            table.add_columns("setting", "value")
            table.add_row("stage", STAGE_LABELS[stage])
            table.add_row("primary", route.primary.label)
            table.add_row("fallback", route.fallback.label)
            table.add_row("profile", route.profile)
            table.add_row("gate", "on" if route.gate_enabled else "off")
            table.add_row("edit", "Press Enter to cycle primary model from configured providers")
        elif mode == "diagnostics":
            table.add_columns("check", "status")
            for provider, status in state.diagnostics.provider_health.items():
                table.add_row(provider, status)
            for missing in state.diagnostics.missing:
                table.add_row(missing, "missing dependency/secret")
        else:
            table.add_columns("field", "value")
            row = state.stages[stage]
            route = row.routing
            table.add_row("stage", row.label)
            table.add_row("status", row.status)
            table.add_row("activity", row.activity)
            table.add_row("primary", route.primary.label if route else "-")
            table.add_row("fallback", route.fallback.label if route else "-")
            table.add_row("worker group", route.worker_group if route else "-")
            table.add_row("workers", str(len(stage_workers(state, stage))))
            table.add_row("artifacts", str(len(stage_artifacts(state, stage))))
            for artifact in stage_artifacts(state, stage):
                table.add_row(f"artifact:{artifact.kind}", artifact.path)
            for worker in stage_workers(state, stage):
                table.add_row(f"worker:{worker.role}", f"{worker.worker_id} {worker.status} {worker.task}")


class Composer(Vertical):
    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("nexussy › type below, then Enter", id="composer-label")
        yield Input(placeholder="Type a message or /command...", id="composer")

    def render_state(self, state: AppState) -> None:
        scope = "nexussy"
        if state.pending_gate:
            scope = "confirm to advance"
        elif state.stage_chat_scope:
            scope = state.stage_chat_scope
        elif state.paused:
            scope = "nexussy (paused)"
        if state.pending_control:
            action, stage = state.pending_control
            scope = f"{action} {stage}"
        self.query_one("#composer-label", Label).update(f"{scope} › type below, then Enter")
        input_widget = self.query_one("#composer", Input)
        input_widget.disabled = False
        if state.interview.question_id and state.interview.suggested_answer and not input_widget.value and not state.interview.waiting:
            input_widget.value = state.interview.suggested_answer

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text and self.app.state.interview.suggested_answer:
            text = "__accept_suggestion__"
        event.input.value = ""
        self.post_message(self.Submitted(text))


class StatusBar(Static):
    def render_state(self, state: AppState) -> None:
        chat = f"chat:{STAGE_LABELS[state.stage_chat_scope]}" if state.stage_chat_scope else "chat:global"
        gate = f" gate:{STAGE_LABELS[state.pending_gate.completed_stage]}" if state.pending_gate else ""
        connection = "● connected" if state.connection == "connected" else "✗ disconnected"
        self.update(f"{connection} | profile {state.profile} | selected {STAGE_LABELS[state.selected_stage]} | {chat}{gate} | Enter: submit | ↑↓: history | {state.status_message}")
