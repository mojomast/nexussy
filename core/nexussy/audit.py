from __future__ import annotations

from pathlib import Path

from nexussy.session import now_utc


def audit_log_path(home_dir: str) -> Path:
    return Path(home_dir).expanduser() / "audit.log"


def write_audit(home_dir: str, action: str, **fields: object) -> None:
    path = audit_log_path(home_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [now_utc().isoformat(), action]
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        text = str(value).replace("\n", " ").replace("\r", " ")
        parts.append(f"{key}={text}")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(" ".join(parts) + "\n")
