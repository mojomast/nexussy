from __future__ import annotations

from nexussy.api.schemas import ArtifactRef, StageName
from nexussy.pipeline.helpers import interview_summary


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.design
    interview_artifact = await engine._latest_interview_artifact(rid)
    interview = interview_summary(interview_artifact)
    prompt = f"Create design with Goals, Architecture, Dependencies, Risks, Test Strategy for: {req.description}\n\n{interview}"
    if interview_artifact and any(q.confidence == "low" for q in interview_artifact.questions):
        prompt = "Some interview answers were auto-generated from a short description and have low confidence. Prefer minimal, conservative design choices. Do not infer features not explicitly stated.\n\n" + prompt
    txt = await engine._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
    fallback = "# Goals\nDeliver requested project.\n# Architecture\nProvider-guided design.\n# Dependencies\nPython.\n# Risks\nUnknowns.\n# Test Strategy\nAutomated tests.\n"
    return [await engine._save_art(rid, sid, root, "design_draft", txt if all(h in txt for h in ["Goals", "Architecture", "Dependencies", "Risks", "Test Strategy"]) else fallback)]
