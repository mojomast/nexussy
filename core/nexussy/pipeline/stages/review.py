from __future__ import annotations

from nexussy.api.schemas import ArtifactRef, ReviewReport, StageName
from nexussy.pipeline.helpers import issues_from_provider_text, provider_declared_passed, review_feedback


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.review
    if req.metadata.get("force_review_fail"):
        report = ReviewReport(passed=False, max_iterations=engine.config.stages.review.max_iterations or 2, feedback_for_plan_stage="Fix plan issues")
        return [await engine._save_art(rid, sid, root, "review_report", report.model_dump_json(indent=2))]
    devplan = await engine._latest_artifact_text(rid, "devplan")
    handoff = await engine._latest_artifact_text(rid, "handoff")
    prompt = (
        "Review this devplan and handoff for missing anchors, unclear next tasks, cross-boundary risks, and readiness for development. "
        "Return JSON with optional issues[] and feedback_for_plan_stage. If clean, return passed true and no issues.\n\n"
        f"DEVPLAN:\n{devplan}\n\nHANDOFF:\n{handoff}"
    )
    response = await engine._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
    issues = issues_from_provider_text(response)
    issue_passed = not any(issue.fix_required or issue.severity in {"error", "blocker"} for issue in issues)
    passed = provider_declared_passed(response, issue_passed) and issue_passed
    report = ReviewReport(passed=passed, max_iterations=engine.config.stages.review.max_iterations or 2, issues=issues, feedback_for_plan_stage=review_feedback(response, issues))
    return [await engine._save_art(rid, sid, root, "review_report", report.model_dump_json(indent=2))]
