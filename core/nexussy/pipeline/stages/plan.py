from __future__ import annotations

import json
import re

from nexussy.api.schemas import ArtifactRef, DevplanTask, ErrorCode, ErrorResponse, SSEEventType, StageName
from nexussy.pipeline.helpers import devplan_with_anchors, devplan_with_task_contract, interview_summary
from nexussy.pipeline.stages.develop import _slice_devplan_tasks, _valid_task_specs


def _extract_json_array(text: str):
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    for candidate in candidates:
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\[", candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
            except Exception:
                continue
            if isinstance(value, list):
                return value
    return None


def _devplan_tasks_json(provider_text: str, devplan: str, validation: str) -> str:
    if validation != "none":
        parsed = _extract_json_array(provider_text)
        if parsed is not None:
            specs = _valid_task_specs(parsed, repair=validation == "repair")
            if specs is not None:
                return json.dumps(specs, indent=2)
            if validation == "strict":
                raise ValueError("devplan_tasks validation failed")
    fallback = _slice_devplan_tasks(devplan)
    return json.dumps([DevplanTask.model_validate(task).model_dump(mode="json") for task in fallback], indent=2)


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.plan
    interview = interview_summary(await engine._latest_interview_artifact(rid))
    review_feedback_for_plan = kwargs.get("review_feedback_for_plan", "")
    feedback = f"\n\nReview feedback to address in this plan retry:\n{review_feedback_for_plan}" if review_feedback_for_plan else ""
    prompt = f"Create a devplan.md body with PROGRESS_LOG and NEXT_TASK_GROUP anchors from interview requirements. ALSO output devplan_tasks.json with exactly this schema: array of objects {{task_id: string, title: string, acceptance_criteria: string, files_allowed: string[], depends_on: string[], owner: string|null, estimated_tokens: int|null}}.\n\n{interview}\n\nOriginal description: {req.description}{feedback}"
    steer = await engine.consume_steer(rid)
    if steer:
        messages = [m.get("message", "") for m in steer if m.get("message")]
        if messages:
            prompt = "## Steering Instructions\n" + "\n".join(messages) + "\n\n" + prompt
    plan_text = await engine._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
    devplan, warned = devplan_with_anchors(plan_text)
    devplan, contract_warned, contract_issues = devplan_with_task_contract(devplan)
    validation = getattr(engine.config.stages.plan, "devplan_task_validation", "repair")
    devplan_tasks_json = _devplan_tasks_json(plan_text, devplan, validation)
    if warned:
        await engine.emit(SSEEventType.pipeline_error, sid, rid, ErrorResponse(error_code=ErrorCode.validation_error, message="plan output required anchor repair", details={"stage": "plan"}, retryable=True))
    if contract_warned:
        await engine.emit(SSEEventType.pipeline_error, sid, rid, ErrorResponse(error_code=ErrorCode.validation_error, message="plan output required task contract repair", details={"stage": "plan", "issues": contract_issues}, retryable=True))
    handoff = """# Handoff
<!-- QUICK_STATUS_START -->
Pipeline plan generated.
<!-- QUICK_STATUS_END -->
<!-- HANDOFF_NOTES_START -->
Continue from devplan.
<!-- HANDOFF_NOTES_END -->
<!-- SUBAGENT_A_ASSIGNMENT_START -->
Own core.
<!-- SUBAGENT_A_ASSIGNMENT_END -->
<!-- SUBAGENT_B_ASSIGNMENT_START -->
Own tui.
<!-- SUBAGENT_B_ASSIGNMENT_END -->
<!-- SUBAGENT_C_ASSIGNMENT_START -->
Own web.
<!-- SUBAGENT_C_ASSIGNMENT_END -->
<!-- SUBAGENT_D_ASSIGNMENT_START -->
Own ops.
<!-- SUBAGENT_D_ASSIGNMENT_END -->
"""
    refs = [await engine._save_art(rid, sid, root, "devplan", devplan), await engine._save_art(rid, sid, root, "devplan_tasks", devplan_tasks_json), await engine._save_art(rid, sid, root, "handoff", handoff)]
    for i in range(1, cp.phase_count + 1):
        refs.append(await engine._save_art(rid, sid, root, "phase", f"# Phase {i:03d}\n<!-- PHASE_TASKS_START -->\n- [ ] Task {i}\n<!-- PHASE_TASKS_END -->\n<!-- PHASE_PROGRESS_START -->\n- pending\n<!-- PHASE_PROGRESS_END -->\n", i))
    return refs
