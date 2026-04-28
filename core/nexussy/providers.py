from __future__ import annotations
import asyncio, os
from dataclasses import dataclass
from datetime import datetime, timezone

from nexussy.api.schemas import ErrorCode, ErrorResponse

DISCOVERY = {"OPENAI_API_KEY":"openai", "ANTHROPIC_API_KEY":"anthropic", "OPENROUTER_API_KEY":"openrouter", "GROQ_API_KEY":"groq", "GEMINI_API_KEY":"google", "MISTRAL_API_KEY":"mistral", "TOGETHER_API_KEY":"together", "FIREWORKS_API_KEY":"fireworks", "XAI_API_KEY":"xai", "GLM_API_KEY":"zai", "ZAI_API_KEY":"zai", "REQUESTY_API_KEY":"requesty", "AETHER_API_KEY":"aether", "OLLAMA_BASE_URL":"ollama"}

def configured_providers(env: dict | None = None) -> list[str]:
    env = env or os.environ
    found = sorted({prefix for key,prefix in DISCOVERY.items() if env.get(key)})
    # Mock mode is production-dangerous unless explicitly enabled.  Hidden tests
    # assert the old implicit fallback is gone; callers may opt in per request via
    # metadata or globally via this env var for local fixtures only.
    if env.get("NEXUSSY_MOCK_PROVIDER", "0") == "1": found.append("mock")
    if env.get("NEXUSSY_PROVIDER_MODE") == "fake": found.append("fake")
    return found

def provider_for_model(model: str) -> str:
    return model.split("/",1)[0] if "/" in model else model

def mock_requested(metadata: dict | None = None, env: dict | None = None) -> bool:
    env = env or os.environ
    metadata = metadata or {}
    return bool(metadata.get("mock_provider") or metadata.get("allow_mock_provider") or env.get("NEXUSSY_MOCK_PROVIDER") == "1")

def model_available(model: str, allow_mock: bool = False, env: dict | None = None) -> bool:
    env = env or os.environ
    if env.get("NEXUSSY_PROVIDER_MODE") == "fake":
        return True
    providers = configured_providers(env)
    return provider_for_model(model) in providers or allow_mock

def select_stage_model(config, stage: str, request_overrides: dict | None = None) -> str:
    """SPEC precedence: request override > stage env/config > provider default."""
    request_overrides = request_overrides or {}
    if stage in request_overrides:
        return request_overrides[stage]
    stage_cfg = getattr(config.stages, stage)
    return getattr(stage_cfg, "model", None) or config.providers.default_model

def provider_error_for_model(model: str, retryable: bool = False) -> ErrorResponse:
    code = ErrorCode.provider_unavailable if "/" not in model else ErrorCode.model_unavailable
    return ErrorResponse(error_code=code, message=f"provider/model unavailable: {model}", details={"model": model, "provider": provider_for_model(model)}, retryable=retryable)

async def persist_rate_limit(db, provider: str, model: str, reset_at: datetime, reason: str):
    created = datetime.now(timezone.utc).isoformat()
    await db.write(lambda con: con.execute("INSERT INTO rate_limits VALUES(?,?,?,?,?)", (provider, model, reset_at.isoformat(), reason, created)))

async def active_rate_limit(db, provider: str, model: str):
    now = datetime.now(timezone.utc).isoformat()
    rows = await db.read("SELECT * FROM rate_limits WHERE provider=? AND model=? AND reset_at>? ORDER BY reset_at DESC LIMIT 1", (provider, model, now))
    return rows[0] if rows else None

@dataclass
class ProviderResult:
    text: str
    usage: dict

async def complete(stage: str, prompt: str, model: str, *, allow_mock: bool = False, timeout_s: int = 120) -> ProviderResult:
    if allow_mock:
        return ProviderResult(text=f"mock {stage} output for {prompt[:40]}", usage={"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model})
    if os.environ.get("NEXUSSY_PROVIDER_MODE") == "fake":
        return ProviderResult(text=f"fake provider {stage} output for {prompt[:80]}", usage={"input_tokens":len(prompt.split()),"output_tokens":8,"cost_usd":0.0,"provider":"fake","model":model})
    try:
        import litellm
    except Exception as e:
        raise RuntimeError("LiteLLM is not installed") from e
    try:
        response = await asyncio.wait_for(litellm.acompletion(model=model, messages=[{"role":"user","content":prompt}]), timeout=timeout_s)
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"provider timeout after {timeout_s}s") from e
    msg = response.choices[0].message.content if getattr(response, "choices", None) else ""
    usage_obj = getattr(response, "usage", None)
    usage = {
        "input_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or getattr(usage_obj, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage_obj, "completion_tokens", 0) or getattr(usage_obj, "output_tokens", 0) or 0),
        "cost_usd": float(getattr(response, "_hidden_params", {}).get("response_cost", 0.0) if hasattr(response, "_hidden_params") else 0.0),
        "provider": provider_for_model(model),
        "model": model,
    }
    return ProviderResult(text=msg or "", usage=usage)
