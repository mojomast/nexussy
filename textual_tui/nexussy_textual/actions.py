from __future__ import annotations

from dataclasses import replace

from .client import CoreClient
from .models import AppState, STAGE_LABELS, StageName
from .state import advance_gate, apply_status_snapshot, close_stage_chat, open_stage_chat, stay_paused


class ActionDispatcher:
    def __init__(self, client: CoreClient) -> None:
        self.client = client

    async def pause_stage(self, state: AppState, stage: StageName) -> AppState:
        if not state.run_id:
            return replace(state, status_message="No active run")
        await self.client.pause(state.run_id, f"pause {stage}")
        return replace(state, paused=True, selected_stage=stage, status_message=f"Paused {STAGE_LABELS[stage]}")

    async def resume_stage(self, state: AppState, stage: StageName) -> AppState:
        if not state.run_id:
            return replace(state, status_message="No active run")
        await self.client.resume(state.run_id)
        return replace(state, paused=False, selected_stage=stage, pending_gate=None, status_message=f"Resumed {STAGE_LABELS[stage]}")

    async def cancel_stage(self, state: AppState, stage: StageName) -> AppState:
        if not state.run_id:
            return replace(state, status_message="No active run")
        await self.client.cancel(state.run_id, f"cancel {stage}")
        return replace(state, selected_stage=stage, status_message=f"Cancelled from {STAGE_LABELS[stage]}")

    async def skip_stage(self, state: AppState, stage: StageName) -> AppState:
        if not state.run_id:
            return replace(state, status_message="No active run")
        await self.client.skip(state.run_id, stage, "user skip from Textual TUI")
        snapshot = await self.client.status(state.run_id)
        return apply_status_snapshot(replace(state, selected_stage=stage), snapshot)

    async def skip_stage_with_reason(self, state: AppState, stage: StageName, reason: str) -> AppState:
        if not state.run_id:
            return replace(state, status_message="No active run", pending_control=None)
        await self.client.skip(state.run_id, stage, reason or "user skip from Textual TUI")
        snapshot = await self.client.status(state.run_id)
        return apply_status_snapshot(replace(state, selected_stage=stage, pending_control=None), snapshot)

    async def send_chat(self, state: AppState, message: str) -> AppState:
        if not message.strip():
            return state
        if state.pending_control:
            action, stage = state.pending_control
            if action == "skip":
                return await self.skip_stage_with_reason(state, stage, message)
            if action == "cancel":
                if message.lower() in {"y", "yes"}:
                    return await self.cancel_stage(replace(state, pending_control=None), stage)
                return replace(state, pending_control=None, status_message="Cancel aborted")
        if state.pending_gate:
            line = message.strip().lower()
            if line in {"y", "yes", "advance", "approve"}:
                return await self.advance_gate(state)
            if line in {"n", "no", "stay", "pause"}:
                return await self.stay_paused(state)
            if not state.run_id:
                return replace(state, status_message="No active run")
            await self.client.inject(state.run_id, message, state.pending_gate.completed_stage)
            return replace(state, status_message=f"Steering {STAGE_LABELS[state.pending_gate.completed_stage]}")
        if state.interview.question_id and state.session_id:
            answer = state.interview.suggested_answer if message == "__accept_suggestion__" else message
            await self.client.interview_answer(state.session_id, {state.interview.question_id: answer})
            return replace(state, status_message="Interview answer submitted", interview=replace(state.interview, waiting=True))
        if not state.run_id:
            result = await self.client.start_pipeline({"project_name": state.project_name, "description": message})
            return replace(state, run_id=result.get("run_id"), session_id=result.get("session_id"), status_message="Pipeline started")
        target_stage = state.stage_chat_scope or (state.pending_gate.completed_stage if state.pending_gate else None)
        await self.client.inject(state.run_id, message, target_stage)
        scope = f" to {STAGE_LABELS[target_stage]}" if target_stage else ""
        return replace(state, status_message=f"Sent{scope}")

    async def advance_gate(self, state: AppState) -> AppState:
        if not state.run_id:
            return advance_gate(state)
        await self.client.resume(state.run_id)
        return advance_gate(state)

    async def stay_paused(self, state: AppState) -> AppState:
        if state.run_id:
            await self.client.pause(state.run_id, "stage gate stay paused")
        return stay_paused(state)

    def open_stage_chat(self, state: AppState, stage: StageName) -> AppState:
        return open_stage_chat(state, stage)

    def close_stage_chat(self, state: AppState) -> AppState:
        return close_stage_chat(state)
