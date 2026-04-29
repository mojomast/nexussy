from __future__ import annotations

from nexussy.api.schemas import ArtifactRef, ErrorCode, ErrorResponse, SSEEventType, StageName
from nexussy.pipeline.helpers import devplan_with_anchors, interview_summary


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.plan
    interview = interview_summary(await engine._latest_interview_artifact(rid))
    review_feedback_for_plan = kwargs.get("review_feedback_for_plan", "")
    feedback = f"\n\nReview feedback to address in this plan retry:\n{review_feedback_for_plan}" if review_feedback_for_plan else ""
    plan_text = await engine._provider_text(st, sid, rid, f"Create a devplan.md body with PROGRESS_LOG and NEXT_TASK_GROUP anchors from interview requirements.\n\n{interview}\n\nOriginal description: {req.description}{feedback}", selected_models, allow_mock)
    devplan, warned = devplan_with_anchors(plan_text)
    if warned:
        await engine.emit(SSEEventType.pipeline_error, sid, rid, ErrorResponse(error_code=ErrorCode.validation_error, message="plan output required anchor repair", details={"stage": "plan"}, retryable=True))
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
    refs = [await engine._save_art(rid, sid, root, "devplan", devplan), await engine._save_art(rid, sid, root, "handoff", handoff)]
    for i in range(1, cp.phase_count + 1):
        refs.append(await engine._save_art(rid, sid, root, "phase", f"# Phase {i:03d}\n<!-- PHASE_TASKS_START -->\n- [ ] Task {i}\n<!-- PHASE_TASKS_END -->\n<!-- PHASE_PROGRESS_START -->\n- pending\n<!-- PHASE_PROGRESS_END -->\n", i))
    return refs
