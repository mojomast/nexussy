from nexussy_textual.models import ModelRef, PendingGate, create_state
from nexussy_textual.state import advance_gate, apply_event, apply_providers, edit_stage_route, open_stage_chat, stage_workers, stay_paused, switch_profile


def env(event_type, payload, sequence=1):
    return {"event_id": f"01ARZ3NDEKTSV4RRFFQ69G5FAV{sequence % 10}", "type": event_type, "run_id": "run-1", "session_id": "sess-1", "payload": payload}


def test_stage_gate_flow_refreshes_stale_gate_to_design():
    state = create_state()
    state = apply_event(state, env("stage_transition", {"from_stage": "interview", "to_stage": "design", "from_status": "passed"}, 1))
    assert state.pending_gate is not None
    assert state.pending_gate.completed_stage == "interview"
    state = apply_event(state, env("artifact_updated", {"artifact": {"kind": "design_draft", "path": ".nexussy/artifacts/design.md"}}, 2))
    state = apply_event(state, env("stage_status", {"stage": "design", "status": "passed"}, 3))
    assert state.pending_gate is not None
    assert state.pending_gate.completed_stage == "design"
    assert state.pending_gate.next_stage == "validate"
    assert ".nexussy/artifacts/design.md" in state.pending_gate.artifacts
    state = advance_gate(state)
    assert state.pending_gate is None


def test_fast_profile_auto_disables_gates():
    state = switch_profile(create_state(), "fast")
    state = apply_event(state, env("stage_transition", {"from_stage": "interview", "to_stage": "design", "from_status": "passed"}, 1))
    assert state.pending_gate is None
    assert all(not stage.gated for stage in state.stages.values())


def test_stage_chat_filters_transcript_scope():
    state = create_state()
    state = apply_event(state, env("content_delta", {"stage": "design", "role": "assistant", "delta": "design text"}, 1))
    state = apply_event(state, env("content_delta", {"stage": "plan", "role": "assistant", "delta": "plan text"}, 2))
    state = open_stage_chat(state, "design")
    from nexussy_textual.state import filtered_transcript

    assert [item.text for item in filtered_transcript(state)] == ["design text"]


def test_provider_auto_population_disables_unconfigured_options():
    state = apply_providers(create_state(), [{"name": "AGENT_ROUTER_TOKEN", "configured": True}])
    labels = [option.label for option in state.model_options]
    assert any("agentrouter/openai/deepseek-v4-flash" in label for label in labels)
    assert any("disabled: missing secret" in label for label in labels)
    disabled = next(option for option in state.model_options if not option.configured)
    next_state = edit_stage_route(state, "design", "primary", disabled)
    assert next_state.routing["design"].primary == state.routing["design"].primary


def test_routing_edit_uses_configured_model_only():
    state = create_state()
    model = ModelRef("mock", "mock-safe", True)
    state = edit_stage_route(state, "plan", "fallback", model)
    assert state.routing["plan"].fallback == model


def test_interview_progression_waiting_state():
    state = create_state()
    state = apply_event(state, env("artifact_updated", {"artifact": {"kind": "interview", "path": "interview.json"}}, 1))
    state = state.__class__(**{**state.__dict__, "interview": state.interview.__class__(question_id="q1", question="What are we building?", suggested_answer="A TUI", answered=0)})
    assert state.interview.question == "What are we building?"
    waiting = state.interview.__class__(**{**state.interview.__dict__, "waiting": True})
    state = state.__class__(**{**state.__dict__, "interview": waiting})
    assert state.interview.waiting is True


def test_worker_filtering_by_stage():
    state = create_state()
    state = apply_event(state, env("worker_spawned", {"worker_id": "backend-abc123", "role": "backend", "stage": "develop", "status": "running", "task_title": "implement"}, 1))
    assert [worker.worker_id for worker in stage_workers(state, "develop")] == ["backend-abc123"]
    assert state.stages["develop"].active_workers == 1


def test_stay_paused_preserves_gate_context():
    state = create_state()
    state = state.__class__(**{**state.__dict__, "pending_gate": PendingGate("design", "validate", "ready"), "paused": True})
    next_state = stay_paused(state)
    assert next_state.pending_gate == state.pending_gate
    assert next_state.paused is True


def test_done_clears_gate_and_sets_final_status():
    state = create_state()
    state = state.__class__(**{**state.__dict__, "pending_gate": PendingGate("develop", None, "ready")})
    state = apply_event(state, env("done", {"final_status": "passed"}, 1))
    assert state.pending_gate is None
    assert state.final_status == "passed"
