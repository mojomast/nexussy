from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

StageName = Literal["interview", "design", "validate", "validate_browser", "plan", "review", "develop"]
StageStatus = Literal["pending", "running", "passed", "failed", "skipped", "blocked", "paused", "retrying"]
ProfileName = Literal["default", "strict", "cheap", "fast"]
ConnectionStatus = Literal["offline", "connecting", "connected", "error"]
PendingControl = tuple[Literal["skip", "cancel"], StageName]

STAGES: tuple[StageName, ...] = ("interview", "design", "validate", "validate_browser", "plan", "review", "develop")
STAGE_LABELS: dict[StageName, str] = {
    "interview": "Interview",
    "design": "Design",
    "validate": "Validate",
    "validate_browser": "Browser Validate",
    "plan": "Plan",
    "review": "Review",
    "develop": "Develop",
}
GATED_PROFILES: dict[ProfileName, bool] = {"default": True, "strict": True, "cheap": True, "fast": False}
STAGE_MODEL_PREFERENCE: dict[StageName, str] = {
    "interview": "fast",
    "design": "smart",
    "validate": "smart",
    "validate_browser": "fast",
    "plan": "smart",
    "review": "smart",
    "develop": "fast",
}


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str
    configured: bool = True
    reason: str = ""

    @property
    def label(self) -> str:
        suffix = "" if self.configured else f" disabled: {self.reason or 'not configured'}"
        return f"{self.provider}/{self.model}{suffix}"


@dataclass(frozen=True)
class StageRouting:
    primary: ModelRef
    fallback: ModelRef
    profile: ProfileName = "default"
    gate_enabled: bool = True
    worker_group: str = "default"


@dataclass(frozen=True)
class StageState:
    name: StageName
    label: str
    status: StageStatus = "pending"
    activity: str = "waiting"
    progress: str = ""
    retrying: bool = False
    skipped: bool = False
    gated: bool = True
    paused: bool = False
    active_workers: int = 0
    routing: StageRouting | None = None


@dataclass(frozen=True)
class PendingGate:
    completed_stage: StageName
    next_stage: StageName | None
    summary: str
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranscriptItem:
    id: str
    stage: StageName | None
    role: Literal["system", "assistant", "user", "worker"]
    text: str
    worker_id: str | None = None


@dataclass(frozen=True)
class WorkerState:
    worker_id: str
    role: str
    stage: StageName | None
    status: str
    task: str = ""


@dataclass(frozen=True)
class ArtifactState:
    kind: str
    path: str
    stage: StageName | None
    updated_at: str = ""


@dataclass(frozen=True)
class ProviderState:
    provider: str
    configured: bool
    models: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class InterviewState:
    question_id: str | None = None
    question: str = ""
    suggested_answer: str = ""
    answered: int = 0
    total_hint: int | None = None
    waiting: bool = False


@dataclass(frozen=True)
class DiagnosticsState:
    provider_health: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppState:
    run_id: str | None = None
    session_id: str | None = None
    project_name: str = "nexussy"
    profile: ProfileName = "default"
    connection: ConnectionStatus = "offline"
    stages: dict[StageName, StageState] = field(default_factory=dict)
    selected_stage: StageName = "interview"
    active_stage: StageName | None = None
    pending_gate: PendingGate | None = None
    stage_chat_scope: StageName | None = None
    transcript: tuple[TranscriptItem, ...] = ()
    workers: dict[str, WorkerState] = field(default_factory=dict)
    artifacts: tuple[ArtifactState, ...] = ()
    providers: tuple[ProviderState, ...] = ()
    routing: dict[StageName, StageRouting] = field(default_factory=dict)
    model_options: tuple[ModelRef, ...] = ()
    interview: InterviewState = field(default_factory=InterviewState)
    diagnostics: DiagnosticsState = field(default_factory=DiagnosticsState)
    paused: bool = False
    final_status: str | None = None
    status_message: str = "Ready"
    focus_return: str | None = None
    command_history: tuple[str, ...] = ()
    history_index: int | None = None
    pending_control: PendingControl | None = None


def default_model_options(providers: tuple[ProviderState, ...] = ()) -> tuple[ModelRef, ...]:
    configured: list[ModelRef] = []
    disabled: list[ModelRef] = []
    for provider in providers:
        target = configured if provider.configured else disabled
        for model in provider.models:
            target.append(ModelRef(provider.provider, model, provider.configured, provider.reason))
    if configured or disabled:
        return tuple(configured + disabled)
    return (ModelRef("mock", "mock-fast", True), ModelRef("mock", "mock-safe", True))


def create_routing(profile: ProfileName, options: tuple[ModelRef, ...]) -> dict[StageName, StageRouting]:
    enabled = [option for option in options if option.configured]
    unconfigured = ModelRef("unconfigured", "none", False, "no provider configured")
    fast_options = [option for option in enabled if any(token in option.model.lower() for token in ("mini", "flash", "fast"))]
    smart_options = [option for option in enabled if option not in fast_options or any(token in option.model.lower() for token in ("opus", "sonnet", "gpt-5"))]
    fast_primary = fast_options[0] if fast_options else (enabled[0] if enabled else unconfigured)
    smart_primary = smart_options[0] if smart_options else fast_primary
    routing: dict[StageName, StageRouting] = {}
    for stage in STAGES:
        primary = smart_primary if STAGE_MODEL_PREFERENCE[stage] == "smart" else fast_primary
        fallback = fast_primary if primary == smart_primary else smart_primary
        routing[stage] = StageRouting(primary=primary, fallback=fallback, profile=profile, gate_enabled=GATED_PROFILES[profile])
    return routing


def create_state(profile: ProfileName = "default") -> AppState:
    options = default_model_options()
    routing = create_routing(profile, options)
    stages = {stage: StageState(stage, STAGE_LABELS[stage], gated=GATED_PROFILES[profile], routing=routing[stage]) for stage in STAGES}
    return AppState(profile=profile, stages=stages, routing=routing, model_options=options)


def replace_stage(state: AppState, stage: StageName, **changes: Any) -> AppState:
    next_stage = replace(state.stages[stage], **changes)
    stages = dict(state.stages)
    stages[stage] = next_stage
    return replace(state, stages=stages)
