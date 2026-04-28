from __future__ import annotations
import os, pathlib, yaml
from .api.schemas import NexussyConfig

ENV_MAP = {
 "NEXUSSY_HOME": ("home_dir",), "NEXUSSY_PROJECTS_DIR": ("projects_dir",), "NEXUSSY_CORE_HOST": ("core","host"),
 "NEXUSSY_CORE_PORT": ("core","port"), "NEXUSSY_WEB_HOST": ("web","host"), "NEXUSSY_WEB_PORT": ("web","port"),
 "NEXUSSY_AUTH_ENABLED": ("auth","enabled"), "NEXUSSY_DATABASE_PATH": ("database","global_path"), "NEXUSSY_DEFAULT_MODEL": ("providers","default_model"),
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
    if raw.lower() in ("true", "false"):
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

def _env_file(path: pathlib.Path) -> dict[str,str]:
    vals={}
    if path.exists():
        for line in path.read_text().splitlines():
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1); vals[k.strip()]=v.strip().strip('"').strip("'")
    return vals

def load_config(overrides: dict | None = None) -> NexussyConfig:
    base = NexussyConfig().model_dump(mode="json")
    cfg_path = pathlib.Path(os.environ.get("NEXUSSY_CONFIG", "~/.nexussy/nexussy.yaml")).expanduser()
    if cfg_path.exists():
        base = _merge(base, yaml.safe_load(cfg_path.read_text()) or {})
    env_path = pathlib.Path(os.environ.get("NEXUSSY_ENV_FILE", "~/.nexussy/.env")).expanduser()
    envs = _env_file(env_path) | dict(os.environ)
    env_patch={}
    for key,path in ENV_MAP.items():
        if key in envs and envs[key] != "": _set(env_patch, path, envs[key])
    base = _merge(base, env_patch)
    if overrides: base = _merge(base, overrides)
    return NexussyConfig.model_validate(base)
