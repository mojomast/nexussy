import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from nexussy.api import server
from nexussy.api.server import app
from nexussy.api.schemas import NexussyConfig, PipelineStartRequest, StageName
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine
from nexussy.pipeline.stages.design import build_design_prompt
from nexussy.providers import ProviderResult


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


@pytest.mark.asyncio
async def test_pipeline_design_stage_injects_stripe_pack_from_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_path / "projects"))
    server.config = load_config()
    server.db = Database(server.config.database.global_path, server.config.database.busy_timeout_ms, server.config.database.write_retry_count, server.config.database.write_retry_base_ms)
    server.engine = Engine(server.db, server.config)
    await server.db.init()
    prompts = []

    async def fake_complete(stage, prompt, model, *, allow_mock=False, timeout_s=120, _env=None, db=None):
        prompts.append((stage.value if hasattr(stage, "value") else stage, prompt))
        usage = {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0, "provider": "mock", "model": model}
        if "Generate a JSON array" in prompt:
            return ProviderResult(json.dumps([{"id": "q1", "question": "What is it?"}, {"id": "q2", "question": "Who uses it?"}, {"id": "q3", "question": "What platform?"}, {"id": "q4", "question": "Any constraints?"}]), usage)
        if "Answer these interview questions" in prompt:
            return ProviderResult(json.dumps({"q1": "billing UI", "q2": "operators", "q3": "web", "q4": "use Stripe-like trust cues"}), usage)
        return ProviderResult("# Goals\nShip UI.\n# Architecture\nWeb.\n# Dependencies\nNone.\n# Risks\nNone.\n# Test Strategy\nTests.\n", usage)

    monkeypatch.setattr("nexussy.pipeline.engine.complete", fake_complete)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/pipeline/start",
            json={
                "project_name": "Stripe Pack Demo",
                "description": "Build a billing dashboard.",
                "auto_approve_interview": True,
                "stop_after_stage": "design",
                "metadata": {"mock_provider": True, "design_context_pack": "stripe"},
            },
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        for _ in range(100):
            events = (await client.get("/events", params={"run_id": run_id})).json()
            if events and events[-1]["type"] == "done":
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("pipeline did not finish")

    design_prompts = [prompt for stage, prompt in prompts if stage == "design"]
    assert design_prompts
    assert "Stripe Design Context Pack" in design_prompts[0]
    assert "Project design request:" in design_prompts[0]
