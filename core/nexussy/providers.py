from __future__ import annotations
import asyncio, logging, os, queue, threading
from email.utils import parsedate_to_datetime
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from nexussy.api.schemas import ErrorCode, ErrorResponse, SecretSummary

logger = logging.getLogger(__name__)

DISCOVERY = {"OPENAI_API_KEY":"openai", "ANTHROPIC_API_KEY":"anthropic", "OPENROUTER_API_KEY":"openrouter", "GROQ_API_KEY":"groq", "GEMINI_API_KEY":"google", "MISTRAL_API_KEY":"mistral", "TOGETHER_API_KEY":"together", "FIREWORKS_API_KEY":"fireworks", "XAI_API_KEY":"xai", "GLM_API_KEY":"zai", "ZAI_API_KEY":"zai", "REQUESTY_API_KEY":"requesty", "AETHER_API_KEY":"aether", "OLLAMA_BASE_URL":"ollama"}  # GLM is an alias for ZAI provider.

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
        return SecretSummary(name=name, source="file", configured=True)
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
    target_path = env_path or env_file_path()
    logger.warning("keyring unavailable; secret %s will be stored as plaintext in %s", name, target_path)
    _write_env_file_value(target_path, name, value)
    os.environ[name] = value
    return SecretSummary(name=name, source="file", configured=True, updated_at=datetime.now(timezone.utc))

def delete_secret(name: str, *, env_path: Path | None = None, service: str = "nexussy") -> bool:
    validate_secret_name(name)
    path = env_path or env_file_path()
    existed = False
    keyring = _keyring_module()
    if keyring:
        sentinel = object()
        deleted = _run_keyring_with_timeout(lambda: keyring.delete_password(service, name), default=sentinel)
        if deleted is not sentinel:
            existed = True
    existed = existed or bool(os.environ.get(name) or read_env_file(path).get(name))
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

def _is_rate_limit_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status == 429 or "ratelimit" in name or "rate_limit" in name or "rate limit" in text or "429" in text or "status 429" in text

def _rate_limit_headers(exc: Exception) -> dict:
    headers = getattr(exc, "headers", None) or getattr(getattr(exc, "response", None), "headers", None) or {}
    return dict(headers) if hasattr(headers, "items") else {}

def _parse_rate_limit_reset(exc: Exception) -> datetime:
    headers = {str(k).lower(): v for k, v in _rate_limit_headers(exc).items()}
    for key in ("x-ratelimit-reset", "x-rate-limit-reset", "retry-after"):
        raw = headers.get(key)
        if raw is None:
            continue
        try:
            seconds = float(raw)
            if key == "retry-after":
                return datetime.now(timezone.utc) + timedelta(seconds=seconds)
            if seconds > 10_000_000:
                return datetime.fromtimestamp(seconds, timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            return parsedate_to_datetime(str(raw)).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc) + timedelta(minutes=1)

async def complete(stage: str, prompt: str, model: str, *, allow_mock: bool = False, timeout_s: int = 120, _env: dict | None = None, db=None) -> ProviderResult:
    if allow_mock:
        return ProviderResult(text=f"mock {stage} output for {prompt[:40]}", usage={"input_tokens":1,"output_tokens":1,"cost_usd":0.0,"provider":"mock","model":model})
    if os.environ.get("NEXUSSY_PROVIDER_MODE") == "fake":
        return ProviderResult(text=f"fake provider {stage} output for {prompt[:80]}", usage={"input_tokens":len(prompt.split()),"output_tokens":8,"cost_usd":0.0,"provider":"fake","model":model})
    try:
        import litellm
    except Exception as e:
        raise RuntimeError("LiteLLM is not installed") from e
    call_env = {k:v for k,v in (_env or effective_secret_env()).items() if k in DISCOVERY and v}
    provider = provider_for_model(model)
    call_kwargs = {}
    for key, name in DISCOVERY.items():
        if name == provider and key.endswith("_API_KEY") and call_env.get(key):
            call_kwargs["api_key"] = call_env[key]
            break
    if provider == "ollama" and call_env.get("OLLAMA_BASE_URL"):
        call_kwargs["api_base"] = call_env["OLLAMA_BASE_URL"]
    try:
        response = await asyncio.wait_for(litellm.acompletion(model=model, messages=[{"role":"user","content":prompt}], **call_kwargs), timeout=timeout_s)
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"provider timeout after {timeout_s}s") from e
    except Exception as e:
        if not _is_rate_limit_error(e):
            raise
        reset_at = _parse_rate_limit_reset(e)
        reason = str(e) or "provider rate limited"
        if db is None:
            logger.warning("provider rate limited for %s/%s but no db was supplied; rate limit was not persisted", provider, model)
            raise
        await persist_rate_limit(db, provider, model, reset_at, reason)
        raise
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
