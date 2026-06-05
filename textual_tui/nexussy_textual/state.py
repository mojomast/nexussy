from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import (
    AppState,
    ArtifactState,
    DiagnosticsState,
    GATED_PROFILES,
    ModelRef,
    PendingGate,
    ProviderState,
    STAGE_LABELS,
    STAGES,
    StageName,
    TranscriptItem,
    WorkerState,
    create_routing,
    default_model_options,
    replace_stage,
)

ARTIFACT_STAGE_PREFIX: tuple[tuple[str, StageName], ...] = (
    ("interview", "interview"),
    ("complexity_profile", "interview"),
    ("design", "design"),
    ("validated_design", "validate"),
    ("validation", "validate"),
    ("validate_browser", "validate_browser"),
    ("devplan", "plan"),
    ("handoff", "plan"),
    ("phase", "plan"),
    ("review", "review"),
    ("develop", "develop"),
    ("merge", "develop"),
    ("changed", "develop"),
)


def stage_for_artifact(kind: str) -> StageName | None:
    for prefix, stage in ARTIFACT_STAGE_PREFIX:
        if kind.startswith(prefix):
            return stage
    return None


def apply_event(state: AppState, env: dict[str, Any]) -> AppState:
    event_type = str(env.get("type", ""))
    payload = env.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    event_id = str(env.get("event_id") or f"event-{len(state.transcript) + 1}")
    state = replace(state, run_id=env.get("run_id") or state.run_id, session_id=env.get("session_id") or state.session_id, connection="connected")
    if event_type == "run_started":
        current = payload.get("current_stage") or "interview"
        if current in STAGES:
            state = replace_stage(state, current, status="running", activity="active")
            state = replace(state, active_stage=current, selected_stage=current, status_message="Run started")
    elif event_type == "stage_transition":
        state = _stage_transition(state, payload, event_id)
    elif event_type == "stage_status":
        stage = payload.get("stage")
        if stage in STAGES:
            status = payload.get("status", "pending")
            state = replace_stage(
                state,
                stage,
                status=status,
                paused=status == "paused",
                retrying=status == "retrying",
                skipped=status == "skipped",
                activity=_activity_for_status(status),
            )
            state = _refresh_stale_gate(state)
    elif event_type == "content_delta":
        stage = payload.get("stage") if payload.get("stage") in STAGES else None
        state = _append_transcript(state, event_id, stage, payload.get("role", "assistant"), str(payload.get("delta", "")), payload.get("worker_id"))
    elif event_type in {"worker_spawned", "worker_status", "worker_task"}:
        state = _worker_event(state, payload)
    elif event_type == "artifact_updated":
        state = _artifact_event(state, payload)
    elif event_type == "pause_state_changed":
        paused = bool(payload.get("paused"))
        stage = payload.get("stage") if payload.get("stage") in STAGES else state.active_stage
        state = replace(state, paused=paused, status_message="Paused" if paused else "Running")
        if stage:
            state = replace_stage(state, stage, status="paused" if paused else "running", paused=paused)
    elif event_type == "pipeline_error":
        state = _append_transcript(state, event_id, None, "system", f"Error: {payload.get('message', 'pipeline error')}")
        state = replace(state, status_message="Pipeline error")
    elif event_type == "done":
        state = replace(state, final_status=str(payload.get("final_status", "passed")), pending_gate=None, status_message="Done")
    return _recount_workers(state)


def apply_status_snapshot(state: AppState, snapshot: dict[str, Any]) -> AppState:
    run = snapshot.get("run", {}) if isinstance(snapshot.get("run"), dict) else {}
    state = replace(state, run_id=run.get("run_id") or state.run_id, session_id=run.get("session_id") or state.session_id, paused=bool(snapshot.get("paused")))
    for row in snapshot.get("stages", []) or []:
        if isinstance(row, dict) and row.get("stage") in STAGES:
            status = row.get("status", "pending")
            state = replace_stage(state, row["stage"], status=status, paused=status == "paused", activity=_activity_for_status(status))
            for artifact in [*(row.get("input_artifacts") or []), *(row.get("output_artifacts") or [])]:
                state = merge_artifact(state, artifact)
    for worker in snapshot.get("workers", []) or []:
        if isinstance(worker, dict):
            state = merge_worker(state, worker)
    return _recount_workers(_refresh_stale_gate(state))


def apply_providers(state: AppState, secrets: list[dict[str, Any]], config: dict[str, Any] | None = None) -> AppState:
    provider_models = {
        "openai": ("gpt-5.4", "gpt-5.4-mini"),
        "anthropic": ("claude-opus-4.5", "claude-sonnet-4.5"),
        "agentrouter": ("openai/deepseek-v4-flash", "openai/gpt-5.4"),
        "mock": ("mock-fast", "mock-safe"),
    }
    configured_names = {str(item.get("name", "")).lower() for item in secrets if item.get("configured")}
    providers = []
    for provider, models in provider_models.items():
        env_names = {provider, f"{provider}_api_key"}
        configured = provider == "mock" or bool(configured_names & env_names) or (provider == "agentrouter" and {"agentrouter_api_key", "agent_router_token"} & configured_names)
        providers.append(ProviderState(provider, configured, models, "missing secret" if not configured else ""))
    options = default_model_options(tuple(providers))
    routing = create_routing(state.profile, options)
    stages = {stage: replace(state.stages[stage], routing=routing[stage], gated=GATED_PROFILES[state.profile]) for stage in STAGES}
    diagnostics = DiagnosticsState(provider_health={p.provider: "ok" if p.configured else "missing" for p in providers}, missing=tuple(p.provider for p in providers if not p.configured and p.provider != "mock"))
    return replace(state, providers=tuple(providers), model_options=options, routing=routing, stages=stages, diagnostics=diagnostics)


def switch_profile(state: AppState, profile: str) -> AppState:
    if profile not in GATED_PROFILES:
        return replace(state, status_message=f"Unknown profile: {profile}")
    routing = create_routing(profile, state.model_options)
    stages = {stage: replace(state.stages[stage], routing=routing[stage], gated=GATED_PROFILES[profile]) for stage in STAGES}
    pending_gate = state.pending_gate if GATED_PROFILES[profile] else None
    return replace(state, profile=profile, routing=routing, stages=stages, pending_gate=pending_gate, status_message=f"Profile: {profile}")


def edit_stage_route(state: AppState, stage: StageName, slot: str, model: ModelRef) -> AppState:
    if not model.configured:
        return replace(state, status_message=f"Cannot select {model.label}")
    current = state.routing[stage]
    updated = replace(current, primary=model) if slot == "primary" else replace(current, fallback=model)
    routing = dict(state.routing)
    routing[stage] = updated
    stages = dict(state.stages)
    stages[stage] = replace(stages[stage], routing=updated)
    return replace(state, routing=routing, stages=stages, status_message=f"Updated {STAGE_LABELS[stage]} {slot}")


def open_stage_chat(state: AppState, stage: StageName) -> AppState:
    return replace(state, stage_chat_scope=stage, selected_stage=stage, status_message=f"Stage chat: {STAGE_LABELS[stage]}")


def close_stage_chat(state: AppState) -> AppState:
    return replace(state, stage_chat_scope=None, status_message="Global transcript")


def advance_gate(state: AppState) -> AppState:
    gate = state.pending_gate
    if gate is None:
        return replace(state, status_message="No pending gate")
    return replace(state, pending_gate=None, paused=False, status_message=f"Advancing after {STAGE_LABELS[gate.completed_stage]}")


def stay_paused(state: AppState) -> AppState:
    return replace(state, paused=True, status_message="Gate kept paused")


def filtered_transcript(state: AppState) -> tuple[TranscriptItem, ...]:
    if state.stage_chat_scope is None:
        return state.transcript
    return tuple(item for item in state.transcript if item.stage == state.stage_chat_scope)


def stage_artifacts(state: AppState, stage: StageName) -> tuple[ArtifactState, ...]:
    return tuple(artifact for artifact in state.artifacts if artifact.stage == stage)


def stage_workers(state: AppState, stage: StageName) -> tuple[WorkerState, ...]:
    return tuple(worker for worker in state.workers.values() if worker.stage == stage)


def _stage_transition(state: AppState, payload: dict[str, Any], event_id: str) -> AppState:
    from_stage = payload.get("from_stage")
    to_stage = payload.get("to_stage")
    if from_stage in STAGES:
        from_status = "retrying" if _is_retry(from_stage, to_stage, payload.get("reason")) else payload.get("from_status", "passed")
        state = replace_stage(state, from_stage, status=from_status, retrying=from_status == "retrying", activity=_activity_for_status(from_status))
        if state.profile != "fast" and from_status == "passed":
            artifacts = tuple(artifact.path for artifact in stage_artifacts(state, from_stage))
            state = replace(state, pending_gate=PendingGate(from_stage, to_stage if to_stage in STAGES else None, f"{STAGE_LABELS[from_stage]} completed.", artifacts), paused=True)
    if to_stage in STAGES:
        state = replace_stage(state, to_stage, status="running", activity="active")
        state = replace(state, active_stage=to_stage, selected_stage=to_stage)
    return _append_transcript(state, event_id, None, "system", f"Stage transition: {from_stage or 'start'} -> {to_stage}")


def _refresh_stale_gate(state: AppState) -> AppState:
    gate = state.pending_gate
    if gate is None or gate.next_stage is None:
        return state
    next_state = state.stages[gate.next_stage]
    if next_state.status in {"passed", "skipped"}:
        next_index = STAGES.index(gate.next_stage)
        following = STAGES[next_index + 1] if next_index + 1 < len(STAGES) else None
        artifacts = tuple(artifact.path for artifact in stage_artifacts(state, gate.next_stage))
        return replace(state, pending_gate=PendingGate(gate.next_stage, following, f"{STAGE_LABELS[gate.next_stage]} completed.", artifacts))
    return state


def _append_transcript(state: AppState, item_id: str, stage: StageName | None, role: str, text: str, worker_id: str | None = None) -> AppState:
    clean_role = role if role in {"system", "assistant", "user", "worker"} else "assistant"
    return replace(state, transcript=(*state.transcript, TranscriptItem(item_id, stage, clean_role, text, worker_id)))


def _worker_event(state: AppState, payload: dict[str, Any]) -> AppState:
    return merge_worker(state, payload)


def merge_worker(state: AppState, payload: dict[str, Any]) -> AppState:
    worker_id = str(payload.get("worker_id") or "")
    if not worker_id:
        return state
    stage = payload.get("stage") if payload.get("stage") in STAGES else _infer_stage(str(payload.get("task_title") or payload.get("task") or ""))
    worker = WorkerState(worker_id=worker_id, role=str(payload.get("role", "worker")), stage=stage, status=str(payload.get("status", "idle")), task=str(payload.get("task_title") or payload.get("task") or ""))
    workers = dict(state.workers)
    workers[worker_id] = worker
    return replace(state, workers=workers)


def _artifact_event(state: AppState, payload: dict[str, Any]) -> AppState:
    artifact = payload.get("artifact")
    return merge_artifact(state, artifact) if isinstance(artifact, dict) else state


def merge_artifact(state: AppState, artifact: dict[str, Any]) -> AppState:
    kind = str(artifact.get("kind", ""))
    path = str(artifact.get("path", ""))
    if not kind or not path:
        return state
    item = ArtifactState(kind=kind, path=path, stage=stage_for_artifact(kind), updated_at=str(artifact.get("updated_at", "")))
    artifacts = tuple(existing for existing in state.artifacts if not (existing.kind == kind and existing.path == path)) + (item,)
    state = replace(state, artifacts=artifacts)
    return _refresh_stale_gate(state)


def _recount_workers(state: AppState) -> AppState:
    stages = dict(state.stages)
    for stage in STAGES:
        count = len([worker for worker in state.workers.values() if worker.stage == stage and worker.status not in {"finished", "failed", "stopped"}])
        stages[stage] = replace(stages[stage], active_workers=count)
    return replace(state, stages=stages)


def _activity_for_status(status: str) -> str:
    return {
        "pending": "waiting",
        "running": "active",
        "paused": "paused by user/gate",
        "retrying": "retrying",
        "passed": "complete",
        "failed": "failed - inspect logs",
        "skipped": "skipped",
        "blocked": "blocked",
    }.get(status, status)


def _is_retry(from_stage: str | None, to_stage: str | None, reason: str | None) -> bool:
    return "retry" in (reason or "").lower() or (from_stage, to_stage) in {("validate", "design"), ("review", "plan")}


def _infer_stage(text: str) -> StageName | None:
    lowered = text.lower()
    for stage in STAGES:
        if stage in lowered or stage.replace("_", " ") in lowered:
            return stage
    return None
