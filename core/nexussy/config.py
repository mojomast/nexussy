from __future__ import annotations
import os, pathlib, warnings, yaml
from .api.schemas import NexussyConfig
from nexussy.providers import read_env_file as _env_file

ENV_MAP = {
 "NEXUSSY_HOME": ("home_dir",), "NEXUSSY_PROJECTS_DIR": ("projects_dir",), "NEXUSSY_CORE_HOST": ("core","host"),
 "NEXUSSY_CORE_PORT": ("core","port"), "NEXUSSY_WEB_HOST": ("web","host"), "NEXUSSY_WEB_PORT": ("web","port"),
 "NEXUSSY_AUTH_ENABLED": ("auth","enabled"), "NEXUSSY_DATABASE_PATH": ("database","global_path"), "NEXUSSY_DEFAULT_MODEL": ("providers","default_model"),
 "NEXUSSY_CORS_ALLOW_ORIGINS": ("core","cors_allow_origins"),
 "NEXUSSY_INTERVIEW_MODEL": ("stages","interview","model"), "NEXUSSY_DESIGN_MODEL": ("stages","design","model"),
 "NEXUSSY_VALIDATE_MODEL": ("stages","validate","model"), "NEXUSSY_PLAN_MODEL": ("stages","plan","model"),
 "NEXUSSY_REVIEW_MODEL": ("stages","review","model"), "NEXUSSY_DEVELOP_MODEL": ("stages","develop","model"),
 "NEXUSSY_ORCHESTRATOR_MODEL": ("stages","develop","orchestrator_model"), "NEXUSSY_PI_COMMAND": ("pi","command"), "NEXUSSY_LOG_LEVEL": ("logging","level"),
}

def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k,v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v,dict) and isinstance(out.get(k),dict) else v
    return out

def _set(d, path, val):
    cur=d
    for p in path[:-1]: cur=cur.setdefault(p,{})
    raw = str(val)
    if path == ("core", "cors_allow_origins"):
        val = [item.strip() for item in raw.split(",") if item.strip()]
    elif raw.lower() in ("true", "false"):
        val = raw.lower() == "true"
    else:
        try:
            val = int(raw)
        except ValueError:
            try:
                val = float(raw)
            except ValueError:
                pass
    cur[path[-1]]=val

def _has_path(d: dict | None, path: tuple[str, ...]) -> bool:
    cur = d or {}
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    return True

def _apply_profile(base: dict, profile: str, *, explicit_pi_command: bool, envs: dict) -> dict:
    if profile not in ("dev", "trusted-lan"):
        raise ValueError("NEXUSSY_PROFILE must be dev or trusted-lan")
    if profile == "dev":
        return base
    base = _merge(base, {"auth": {"enabled": True}})
    origins = base.get("core", {}).get("cors_allow_origins") or []
    if "*" in origins:
        raise ValueError("trusted-lan profile rejects wildcard CORS")
    api_key_env = base.get("auth", {}).get("api_key_env", "NEXUSSY_API_KEY")
    if not envs.get(api_key_env):
        raise ValueError(f"trusted-lan profile requires {api_key_env}")
    if not explicit_pi_command:
        raise ValueError("trusted-lan profile requires explicit pi.command or NEXUSSY_PI_COMMAND")
    if base.get("pi", {}).get("command") == "nexussy-pi":
        warnings.warn("trusted-lan profile is using bundled nexussy-pi; configure a sandboxed executor", RuntimeWarning, stacklevel=2)
    home = base.get("home_dir", "~/.nexussy")
    logging_cfg = base.setdefault("logging", {})
    for key, name in (("core_log_file", "core.log"), ("web_log_file", "web.log"), ("tui_log_file", "tui.log")):
        if str(logging_cfg.get(key, "")).startswith("/tmp/"):
            logging_cfg[key] = str(pathlib.Path(home).expanduser() / "logs" / name)
    return base

def load_config(overrides: dict | None = None) -> NexussyConfig:
    base = NexussyConfig().model_dump(mode="json")
    cfg_path = pathlib.Path(os.environ.get("NEXUSSY_CONFIG", "~/.nexussy/nexussy.yaml")).expanduser()
    yaml_cfg = {}
    if cfg_path.exists():
        yaml_cfg = yaml.safe_load(cfg_path.read_text()) or {}
        base = _merge(base, yaml_cfg)
    env_path = pathlib.Path(os.environ.get("NEXUSSY_ENV_FILE", "~/.nexussy/.env")).expanduser()
    envs = _env_file(env_path) | dict(os.environ)
    env_patch={}
    for key,path in ENV_MAP.items():
        if key in envs and envs[key] != "": _set(env_patch, path, envs[key])
    base = _merge(base, env_patch)
    if overrides: base = _merge(base, overrides)
    profile = str(envs.get("NEXUSSY_PROFILE", "dev") or "dev").strip().lower()
    explicit_pi_command = _has_path(yaml_cfg, ("pi", "command")) or bool(envs.get("NEXUSSY_PI_COMMAND")) or _has_path(overrides, ("pi", "command"))
    base = _apply_profile(base, profile, explicit_pi_command=explicit_pi_command, envs=envs)
    return NexussyConfig.model_validate(base)
