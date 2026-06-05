from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Label, ListItem, ListView, RichLog, Static

from .models import AppState, STAGE_LABELS, STAGES, StageName
from .state import filtered_transcript, stage_artifacts, stage_workers

STATUS_TOKENS = {
    "running": ("●", "RUN", "running"),
    "passed": ("✓", "OK", "passed"),
    "failed": ("✗", "FAIL", "failed"),
    "paused": ("Ⅱ", "PAUSE", "paused"),
    "pending": ("○", "WAIT", "pending"),
    "retrying": ("↻", "RETRY", "retrying"),
    "skipped": ("○", "SKIP", "skipped"),
    "blocked": ("⏸", "BLOCK", "blocked"),
}


def status_token(status: str, gated: bool = False) -> str:
    if gated:
        return "⏸ GATE gated"
    icon, label, text = STATUS_TOKENS.get(status, ("○", status.upper()[:5], status))
    return f"{icon} {label} {text}"


def short_model(label: str) -> str:
    base = label.split(" disabled:", 1)[0]
    if "/" in base:
        provider, model = base.split("/", 1)
        return f"{provider[:3]}/{model.split('/')[-1][:14]}"
    return base[:18]


class HeaderBar(Static):
    def render_state(self, state: AppState) -> None:
        active = STAGE_LABELS[state.active_stage] if state.active_stage else "No run"
        health = ", ".join(f"{k}:{v}" for k, v in sorted(state.diagnostics.provider_health.items())) or "providers unknown"
        self.update(f"nexussy | {active} | profile {state.profile} | run {state.run_id or 'not started'} | {health}")


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
        for index, stage in enumerate(STAGES, start=1):
            row = state.stages[stage]
            route = row.routing
            model = short_model(route.primary.label if route else "-")
            gated = bool(state.pending_gate and state.pending_gate.next_stage == stage)
            selected = state.selected_stage == stage
            active = state.active_stage == stage
            cursor = "▶" if active else ("›" if selected else " ")
            line = f"{cursor} {status_token(row.status, gated).split()[0]} {row.label:<16} {row.status:<8} {model:<18} w:{row.active_workers}"
            detail = ""
            if selected:
                active_note = "active" if active else "selected"
                detail = f"\n   {active_note} | {row.activity} | fallback {short_model(route.fallback.label if route else '-')} | {status_token(row.status, gated)}"
            text = line + detail
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
        self._current_stage: StageName = "interview"
        yield Label("Next Actions", classes="panel-title")
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
        self._current_stage = stage
        row = state.stages[stage]
        route = row.routing
        gated_here = bool(state.pending_gate and state.pending_gate.completed_stage == stage)
        self.query_one("#pause", Button).disabled = state.paused or row.status not in {"running", "retrying"}
        self.query_one("#resume", Button).disabled = not state.paused and not bool(state.pending_gate)
        self.query_one("#advance-gate", Button).display = gated_here
        self.query_one("#resume", Button).display = state.paused or bool(state.pending_gate)
        self.query_one("#pause", Button).display = row.status in {"running", "retrying"} and not state.paused
        self.query_one("#stage-detail", Static).update(
            f"{row.label}: {status_token(row.status, gated_here)} | model {short_model(route.primary.label if route else '-')} | artifacts {len(stage_artifacts(state, stage))} | workers {len(stage_workers(state, stage))}\nLikely next: {likely_action(state, stage)}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = str(event.button.id)
        self.post_message(self.StageAction(action, getattr(self, "_current_stage", "interview")))


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
        self.query_one("#gate-summary", Static).update(f"⏸ GATE {STAGE_LABELS[gate.completed_stage]} -> {next_step}\nSummary: {gate.summary}\nArtifacts: {artifacts}\nNext: type yes to advance, or type feedback to iterate.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.post_message(self.GateAction(str(event.button.id)))


class TranscriptPanel(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_count = 0
        self._last_scope: StageName | None = None

    def compose(self) -> ComposeResult:
        yield Label("Transcript", classes="panel-title")
        yield RichLog(id="transcript-log", wrap=True, highlight=True)

    def render_state(self, state: AppState) -> None:
        log = self.query_one(RichLog)
        items = filtered_transcript(state)[-80:]
        scope_changed = state.stage_chat_scope != self._last_scope
        if scope_changed:
            log.clear()
            self._last_count = 0
            self._last_scope = state.stage_chat_scope
            title = f"Viewing stage: {STAGE_LABELS[state.stage_chat_scope]}" if state.stage_chat_scope else "Global transcript"
            log.write(title)
        if not items and self._last_count == 0:
            log.write("Start here: type a project description below, then press Enter.")
            log.write("Use j/k to select stages, c for stage chat, ? for help, Ctrl+P for commands.")
        new_items = items[self._last_count:]
        for item in new_items:
            scope = f"[{STAGE_LABELS[item.stage][:3].upper()}] " if item.stage else "[RUN] "
            worker = f" {item.worker_id}" if item.worker_id else ""
            role = {"system": "sys", "assistant": "ai", "user": "you", "worker": "wrk"}.get(item.role, item.role)
            prefix = "·" if item.role in {"system", "worker"} else "»"
            log.write(f"{prefix} {scope}{role}{worker}: {item.text}")
        self._last_count = len(items)


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
        yield Static("Stage summary. Open artifacts/workers/routing for details.", id="inspector-hint")
        yield DataTable(id="inspector-table")

    def render_state(self, state: AppState, mode: str = "artifacts") -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        stage = state.selected_stage
        hint = self.query_one("#inspector-hint", Static)
        if mode == "workers":
            hint.update("Workers for selected stage. Empty means no active workers yet.")
            table.add_columns("worker", "role", "stage", "status", "task")
            workers = stage_workers(state, stage)
            if not workers:
                table.add_row("none", "-", STAGE_LABELS[stage], "idle", "Workers appear during develop or explicit spawn.")
            for worker in workers:
                table.add_row(worker.worker_id, worker.role, worker.stage or "-", worker.status, worker.task)
        elif mode == "routing":
            hint.update("Routing for selected stage. Enter cycles primary model from configured options.")
            route = state.routing[stage]
            table.add_columns("setting", "value")
            table.add_row("stage", STAGE_LABELS[stage])
            table.add_row("primary", route.primary.label)
            table.add_row("fallback", route.fallback.label)
            table.add_row("profile", route.profile)
            table.add_row("gate", "on" if route.gate_enabled else "off")
            table.add_row("edit", "Press Enter to cycle primary model from configured providers")
        elif mode == "diagnostics":
            hint.update("Actionable health checks. Configure missing providers before live runs.")
            table.add_columns("check", "status")
            if not state.diagnostics.provider_health:
                table.add_row("core", "No diagnostics yet. Start core with ./nexussy.sh start.")
            for provider, status in state.diagnostics.provider_health.items():
                fix = "ready" if status == "ok" else "add API key in provider setup"
                table.add_row(provider, f"{status} - {fix}")
            for missing in state.diagnostics.missing:
                table.add_row(missing, "missing secret - configure before selecting this provider")
        elif mode == "logs":
            hint.update("Recent transcript lines. System/worker messages are condensed.")
            table.add_columns("stage", "role", "worker", "text")
            items = filtered_transcript(state)[-50:]
            if not items:
                table.add_row("global", "system", "-", "No logs yet. Submit a description to begin.")
            for item in items:
                stage_label = STAGE_LABELS[item.stage] if item.stage else "global"
                table.add_row(stage_label, item.role, item.worker_id or "-", item.text[:80])
        else:
            hint.update("Selected stage at a glance. Press a/w/l/r/d for deeper views.")
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
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_suggested = ""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("nexussy › type below, then Enter", id="composer-label")
        yield Input(placeholder="Type a message or /command...", id="composer")

    def render_state(self, state: AppState) -> None:
        scope = "nexussy"
        placeholder = "Describe what to build, then press Enter..."
        if state.pending_gate:
            scope = "confirm to advance"
            placeholder = "Type yes to advance, no to pause, or feedback to iterate..."
        elif state.stage_chat_scope:
            scope = state.stage_chat_scope
            placeholder = f"Message {STAGE_LABELS[state.stage_chat_scope]} stage..."
        elif state.paused:
            scope = "nexussy (paused)"
            placeholder = "Type steering feedback, or use Resume/Advance..."
        if state.pending_control:
            action, stage = state.pending_control
            scope = f"{action} {stage}"
            placeholder = f"Enter {action} reason/confirmation for {STAGE_LABELS[stage]}..."
        helper = "Enter starts a run" if not state.run_id else "Enter sends to current scope"
        self.query_one("#composer-label", Label).update(f"{scope} › {helper}")
        input_widget = self.query_one("#composer", Input)
        input_widget.placeholder = placeholder
        input_widget.disabled = False
        new_suggestion = state.interview.suggested_answer
        if new_suggestion and not input_widget.value and not state.interview.waiting and new_suggestion != self._last_suggested:
            input_widget.value = new_suggestion
            self._last_suggested = new_suggestion

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
        active = STAGE_LABELS[state.active_stage] if state.active_stage else "no active stage"
        selected = STAGE_LABELS[state.selected_stage]
        self.update(f"{connection} | active {active} | selected {selected} | {chat}{gate} | Enter submits | ? help | {state.status_message}")


def likely_action(state: AppState, stage: StageName) -> str:
    if state.pending_gate and state.pending_gate.completed_stage == stage:
        return "Review artifacts, then Advance or Chat"
    if state.paused:
        return "Resume or send steering feedback"
    status = state.stages[stage].status
    if status in {"running", "retrying"}:
        return "Watch progress or open Stage Chat"
    if status == "failed":
        return "Open Logs or Diagnostics"
    if status == "pending" and not state.run_id:
        return "Type a project description"
    return "Select another stage or inspect details"
