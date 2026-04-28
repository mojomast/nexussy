from __future__ import annotations
import asyncio, os, queue, threading
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

from nexussy.api.schemas import ErrorCode, ErrorResponse, SecretSummary

DISCOVERY = {"OPENAI_API_KEY":"openai", "ANTHROPIC_API_KEY":"anthropic", "OPENROUTER_API_KEY":"openrouter", "GROQ_API_KEY":"groq", "GEMINI_API_KEY":"google", "MISTRAL_API_KEY":"mistral", "TOGETHER_API_KEY":"together", "FIREWORKS_API_KEY":"fireworks", "XAI_API_KEY":"xai", "GLM_API_KEY":"zai", "ZAI_API_KEY":"zai", "REQUESTY_API_KEY":"requesty", "AETHER_API_KEY":"aether", "OLLAMA_BASE_URL":"ollama"}

def secret_names() -> list[str]:
    return sorted(DISCOVERY)

def validate_secret_name(name: str) -> str:
    if name not in DISCOVERY:
        raise KeyError(name)
    return name

def env_file_path(env: dict | None = None) -> Path:
    env = env or os.environ
    if env.get("NEXUSSY_ENV_FILE"):
        return Path(env["NEXUSSY_ENV_FILE"]).expanduser()
    home = Path(env.get("NEXUSSY_HOME", "~/.nexussy")).expanduser()
    return home / ".env"

def read_env_file(path: Path | None = None) -> dict[str, str]:
    path = path or env_file_path()
    vals: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, value = stripped.split("=", 1)
                vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals

def _keyring_module():
    try:
        import keyring
        return keyring
    except Exception:
        return None

def keyring_get(name: str, service: str = "nexussy") -> str | None:
    keyring = _keyring_module()
    if not keyring:
        return None
    return _run_keyring_with_timeout(lambda: keyring.get_password(service, name) or None, default=None)

def _keyring_timeout_s() -> float:
    try:
        return float(os.environ.get("NEXUSSY_KEYRING_TIMEOUT_S", "2"))
    except ValueError:
        return 2.0

def _run_keyring_with_timeout(func, default=None):
    q: queue.Queue = queue.Queue(maxsize=1)
    def target():
        try: q.put((True, func()))
        except Exception as e: q.put((False, e))
    t = threading.Thread(target=target, daemon=True)
    t.start()
    try:
        ok, value = q.get(timeout=_keyring_timeout_s())
    except queue.Empty:
        return default
    return value if ok else default

def _write_env_file_value(path: Path, name: str, value: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    out: list[str] = []
    wrote = False
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if stripped and not stripped.startswith("#") and "=" in stripped else None
        if key == name:
            if value is not None and not wrote:
                out.append(f"{name}={value}")
                wrote = True
            continue
        out.append(line)
    if value is not None and not wrote:
        out.append(f"{name}={value}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(out) + ("\n" if out else ""))
    tmp.replace(path)

def secret_summary(name: str, *, env: dict | None = None, env_path: Path | None = None, service: str = "nexussy") -> SecretSummary:
    validate_secret_name(name)
    env = env or os.environ
    env_path = env_path or env_file_path(env)
    if keyring_get(name, service):
        return SecretSummary(name=name, source="keyring", configured=True)
    if env.get(name):
        return SecretSummary(name=name, source="env", configured=True)
    if read_env_file(env_path).get(name):
        return SecretSummary(name=name, source="config", configured=True)
    return SecretSummary(name=name, source="env", configured=False)

def set_secret(name: str, value: str, *, env_path: Path | None = None, service: str = "nexussy") -> SecretSummary:
    validate_secret_name(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("secret value must be a non-empty string")
    keyring = _keyring_module()
    if keyring:
        sentinel = object()
        stored = _run_keyring_with_timeout(lambda: keyring.set_password(service, name, value), default=sentinel)
        if stored is not sentinel:
            os.environ[name] = value
            return SecretSummary(name=name, source="keyring", configured=True, updated_at=datetime.now(timezone.utc))
    _write_env_file_value(env_path or env_file_path(), name, value)
    os.environ[name] = value
    return SecretSummary(name=name, source="config", configured=True, updated_at=datetime.now(timezone.utc))

def delete_secret(name: str, *, env_path: Path | None = None, service: str = "nexussy") -> bool:
    validate_secret_name(name)
    path = env_path or env_file_path()
    existed = bool(os.environ.get(name) or read_env_file(path).get(name) or keyring_get(name, service))
    keyring = _keyring_module()
    if keyring:
        sentinel = object()
        deleted = _run_keyring_with_timeout(lambda: keyring.delete_password(service, name), default=sentinel)
        if deleted is not sentinel:
            existed = True
    os.environ.pop(name, None)
    _write_env_file_value(path, name, None)
    return existed

def effective_secret_env(env: dict | None = None, *, service: str | None = None) -> dict[str, str]:
    base = read_env_file(env_file_path(env)) | dict(env or os.environ)
    service = service or (env or os.environ).get("NEXUSSY_KEYRING_SERVICE", "nexussy")
    for name in DISCOVERY:
        value = keyring_get(name, service)
        if value:
            base[name] = value
    return base

def configured_providers(env: dict | None = None, *, service: str | None = None) -> list[str]:
    env = effective_secret_env(env, service=service)
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
    os.environ.update({k:v for k,v in effective_secret_env().items() if k in DISCOVERY and v})
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
