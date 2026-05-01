import pytest
from pydantic import ValidationError

from nexussy.api.schemas import NexussyConfig, PipelineStartRequest, StageName
from nexussy.config import load_config
from nexussy.pipeline.stages.design import build_design_prompt


class _Engine:
    def __init__(self, pack=None):
        self.config = NexussyConfig.model_validate({"stages": {"design": {"context_pack": pack}}})


def test_design_context_pack_default_preserves_current_behavior(monkeypatch):
    monkeypatch.delenv("NEXUSSY_DESIGN_CONTEXT_PACK", raising=False)
    cfg = load_config()
    assert cfg.stages.design.context_pack is None


def test_design_context_pack_accepts_builtin_pack_names():
    for pack in ("stripe", "linear", "minimal"):
        cfg = NexussyConfig.model_validate({"stages": {"design": {"context_pack": pack}}})
        assert cfg.stages.design.context_pack == pack


def test_design_context_pack_rejects_invalid_configured_pack():
    with pytest.raises(ValidationError):
        NexussyConfig.model_validate({"stages": {"design": {"context_pack": "brutalist"}}})
    with pytest.raises(ValidationError):
        load_config({"stages": {"design": {"context_pack": "none"}}})


def test_design_context_pack_env_config(monkeypatch):
    monkeypatch.setenv("NEXUSSY_DESIGN_CONTEXT_PACK", "linear")
    cfg = load_config()
    assert cfg.stages.design.context_pack == "linear"


def test_pipeline_metadata_convention_for_design_pack_selection():
    request = PipelineStartRequest(
        project_name="Demo",
        description="Build a demo product landing page.",
        start_stage=StageName.design,
        metadata={"design_context_pack": "stripe"},
    )
    assert request.metadata["design_context_pack"] == "stripe"


def test_design_prompt_without_pack_preserves_existing_prefix():
    req = PipelineStartRequest(project_name="Demo", description="Build billing UI", start_stage=StageName.design)
    prompt = build_design_prompt(_Engine(), req, "Interview: none")
    assert prompt == "Create design with Goals, Architecture, Dependencies, Risks, Test Strategy for: Build billing UI\n\nInterview: none"


def test_design_prompt_injects_configured_pack():
    req = PipelineStartRequest(project_name="Demo", description="Build billing UI", start_stage=StageName.design)
    prompt = build_design_prompt(_Engine("stripe"), req, "Interview: none")
    assert "Stripe Design Context Pack" in prompt
    assert "Project design request:" in prompt
    assert "Build billing UI" in prompt


def test_design_prompt_metadata_override_wins_over_config():
    req = PipelineStartRequest(
        project_name="Demo",
        description="Build issue tracker",
        start_stage=StageName.design,
        metadata={"design_context_pack": "linear"},
    )
    prompt = build_design_prompt(_Engine("stripe"), req, "Interview: none")
    assert "Linear Design Context Pack" in prompt
    assert "Stripe Design Context Pack" not in prompt


def test_design_prompt_metadata_none_disables_configured_pack():
    req = PipelineStartRequest(
        project_name="Demo",
        description="Build plain docs",
        start_stage=StageName.design,
        metadata={"design_context_pack": "none"},
    )
    assert "Design Context Pack" not in build_design_prompt(_Engine("minimal"), req, "Interview: none")


def test_design_prompt_rejects_invalid_metadata_pack():
    req = PipelineStartRequest(
        project_name="Demo",
        description="Build app",
        start_stage=StageName.design,
        metadata={"design_context_pack": "brutalist"},
    )
    with pytest.raises(ValueError, match="invalid design_context_pack"):
        build_design_prompt(_Engine(), req, "Interview: none")
