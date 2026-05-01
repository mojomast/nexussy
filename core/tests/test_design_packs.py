import pytest
from pydantic import ValidationError

from nexussy.api.schemas import NexussyConfig, PipelineStartRequest, StageName
from nexussy.config import load_config


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
