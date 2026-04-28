from __future__ import annotations
import os, re, pathlib

SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_-]{12,})"), re.compile(r"(Bearer\s+)[A-Za-z0-9._~-]+", re.I),
    re.compile(r"(api[_-]?key\s*[=:]\s*)\S+", re.I), re.compile(r"(password\s*[=:]\s*)\S+", re.I),
    re.compile(r"((?:OPENAI|ANTHROPIC|OPENROUTER|GROQ|GEMINI|MISTRAL|TOGETHER|FIREWORKS|XAI|GLM|ZAI|REQUESTY|AETHER)_API_KEY\s*[=:]\s*)\S+", re.I),
    re.compile(r"(gh[ps]_[A-Za-z0-9_]{36,})"),
    re.compile(r"\b[a-f0-9]{40,63}\b"),
    re.compile(r"((?i:(?:token|secret|access_token)\s*[=:]\s*))[a-f0-9]{40,64}\b"),
    re.compile(r"(ssh-rsa\s+|ssh-ed25519\s+)[A-Za-z0-9+/=]+(?:\s+\S+)?", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]

def scrub_log(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", out)
    return out

def sanitize_relative_path(path: str) -> str:
    if "\x00" in path or path.startswith("/"):
        raise ValueError("path_rejected")
    p = pathlib.PurePosixPath(path)
    if any(part in ("..", "") for part in p.parts):
        raise ValueError("path_rejected")
    return str(p)

def sanitize_path(path: str, allowed_roots: list[str], reject_symlink_escape: bool = True) -> pathlib.Path:
    raw = pathlib.Path(path).expanduser()
    resolved = raw.resolve(strict=False)
    roots = [pathlib.Path(r).expanduser().resolve(strict=False) for r in allowed_roots]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError("path_rejected")
    if reject_symlink_escape and raw.exists():
        real = raw.resolve(strict=True)
        if not any(real == root or root in real.parents for root in roots):
            raise ValueError("path_rejected")
    return resolved
