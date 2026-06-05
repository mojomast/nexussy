from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Label, Static

from .models import AppState, STAGE_LABELS, STAGES


KEYMAP_ROWS = [
    ("Tab / Shift+Tab", "Move focus in visual order"),
    ("Arrows / h j k l", "Move between stages or focused lists"),
    ("Enter", "Activate focused control or submit composer"),
    ("Esc", "Close overlay or leave stage chat"),
    ("Ctrl+P", "Command palette"),
    ("?", "Help"),
    ("c", "Open focused stage chat"),
    ("a", "Artifacts inspector"),
    ("w", "Workers inspector"),
    ("l", "Logs/transcript"),
    ("r", "Routing/settings"),
    ("d", "Diagnostics"),
    ("p/u/x/s", "Pause, resume, cancel, skip selected stage"),
    ("y/n", "Advance gate or stay paused"),
]

COMMAND_ROWS = [
    ("Stage chat", "c", "Open chat scoped to selected stage"),
    ("Artifacts", "a", "Show selected stage artifacts"),
    ("Workers", "w", "Show selected stage workers"),
    ("Routing", "r", "Open routing/settings matrix"),
    ("Diagnostics", "d", "Show provider health and missing dependencies"),
    ("Pause stage", "p", "Pause selected stage"),
    ("Resume stage", "u", "Resume run/stage"),
    ("Cancel", "x", "Cancel active run"),
    ("Skip stage", "s", "Skip selected stage"),
    ("Advance gate", "y", "Explicitly approve pending gate"),
    ("Stay paused", "n", "Keep gate paused with context preserved"),
    ("Help", "?", "Open keyboard help"),
]


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close help")]

    def compose(self) -> ComposeResult:
        yield Static("Keyboard Help", classes="modal-title")
        table = DataTable()
        table.add_columns("Key", "Action")
        for row in KEYMAP_ROWS:
            table.add_row(*row)
        yield table
        yield Static("All visible buttons are also reachable by Tab and Enter. Escape returns focus to the invoking area.")


class CommandPaletteScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close commands")]

    def compose(self) -> ComposeResult:
        yield Static("Command Palette", classes="modal-title")
        table = DataTable()
        table.add_columns("Command", "Key", "Description")
        for row in COMMAND_ROWS:
            table.add_row(*row)
        yield table
        yield Static("Use the listed key or Tab to the visible control. This palette is discoverability-first; actions stay visible in the main UI.")


class RoutingScreen(Screen[None]):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.snapshot = state

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(f"Routing and Settings | active profile: {self.snapshot.profile}")
        table = DataTable()
        table.add_columns("stage", "primary", "fallback", "profile", "gate", "provider status")
        for stage in STAGES:
            route = self.snapshot.routing[stage]
            status = "configured" if route.primary.configured else route.primary.reason
            table.add_row(STAGE_LABELS[stage], route.primary.label, route.fallback.label, route.profile, "enabled" if route.gate_enabled else "disabled", status)
        yield table
        yield Footer()


class SimpleTableScreen(Screen[None]):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, title: str, columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        super().__init__()
        self.title = title
        self.columns = columns
        self.rows = rows

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(self.title)
        table = DataTable()
        table.add_columns(*self.columns)
        for row in self.rows:
            table.add_row(*row)
        yield table
        yield Footer()
