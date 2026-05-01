from __future__ import annotations

from importlib import resources
from typing import Literal

from nexussy.api.schemas import ArtifactRef, StageName
from nexussy.pipeline.helpers import interview_summary

DesignPackName = Literal["stripe", "linear", "minimal"]
DESIGN_PACKS: set[str] = {"stripe", "linear", "minimal"}


def _selected_design_pack(engine, req) -> str | None:
    """Resolve request metadata before config without changing the no-pack prompt."""

    metadata = getattr(req, "metadata", {})
    raw = metadata.get("design_context_pack") if isinstance(metadata, dict) else None
    if raw is None or raw == "":
        return getattr(getattr(getattr(getattr(engine, "config", None), "stages", None), "design", None), "context_pack", None)
    if raw == "none":
        return None
    if raw not in DESIGN_PACKS:
        raise ValueError("invalid design_context_pack; expected stripe, linear, minimal, or none")
    return str(raw)


def _load_design_pack(name: str) -> str:
    if name not in DESIGN_PACKS:
        raise ValueError("invalid design context pack")
    try:
        return resources.files("nexussy.assets.design_packs").joinpath(f"{name}.md").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"design context pack asset missing: {name}") from exc


def build_design_prompt(engine, req, interview: str, interview_low_confidence: bool = False) -> str:
    prompt = f"Create design with Goals, Architecture, Dependencies, Risks, Test Strategy for: {req.description}\n\n{interview}"
    pack = _selected_design_pack(engine, req)
    if pack:
        prompt = f"Use the following design context pack as product/UI guidance. Do not copy it verbatim; apply it where relevant.\n\n{_load_design_pack(pack)}\n\nProject design request:\n{prompt}"
    if interview_low_confidence:
        prompt = "Some interview answers were auto-generated from a short description and have low confidence. Prefer minimal, conservative design choices. Do not infer features not explicitly stated.\n\n" + prompt
    return prompt


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.design
    interview_artifact = await engine._latest_interview_artifact(rid)
    interview = interview_summary(interview_artifact)
    prompt = build_design_prompt(engine, req, interview, bool(interview_artifact and any(q.confidence == "low" for q in interview_artifact.questions)))
    txt = await engine._provider_text(st, sid, rid, prompt, selected_models, allow_mock)
    fallback = "# Goals\nDeliver requested project.\n# Architecture\nProvider-guided design.\n# Dependencies\nPython.\n# Risks\nUnknowns.\n# Test Strategy\nAutomated tests.\n"
    return [await engine._save_art(rid, sid, root, "design_draft", txt if all(h in txt for h in ["Goals", "Architecture", "Dependencies", "Risks", "Test Strategy"]) else fallback)]
