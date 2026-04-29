from __future__ import annotations

from nexussy.api.schemas import ArtifactRef, StageName, ValidationReport
from nexussy.pipeline.helpers import corrected_design, issues_from_provider_text, provider_declared_passed


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.validate
    design = await engine._latest_artifact_text(rid, "design_draft")
    prompt = (
        "Validate this design draft for completeness, internal consistency, missing dependencies, risks, and testability. "
        "Return JSON with optional issues[] and optional corrected_design. If clean, return passed true and no issues.\n\n" + design
    )
    response = await engine._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
    issues = issues_from_provider_text(response)
    corrected = corrected_design(response, design)
    issue_passed = not any(issue.fix_required or issue.severity in {"error", "blocker"} for issue in issues)
    report = ValidationReport(passed=provider_declared_passed(response, issue_passed) and issue_passed, max_iterations=engine.config.stages.validate.max_iterations or 3, issues=issues, corrected=corrected.strip() != design.strip())
    return [await engine._save_art(rid, sid, root, "validated_design", corrected), await engine._save_art(rid, sid, root, "validation_report", report.model_dump_json(indent=2))]
