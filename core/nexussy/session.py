from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class SessionStatus(str, Enum):
    created = "created"
    running = "running"
    paused = "paused"
    passed = "passed"
    failed = "failed"
    cancelled = "cancelled"


def now_utc() -> datetime:
    """Return the canonical timezone-aware UTC timestamp used by core models."""
    return datetime.now(timezone.utc)


async def transition_session_status(db, session_id: str, new_status: SessionStatus):
    await db.write(lambda con: con.execute(
        "UPDATE sessions SET status=?, updated_at=? WHERE session_id=?",
        (new_status.value, now_utc().isoformat(), session_id),
    ))


def slugify(name: str) -> str:
    """Backwards-compatible lazy proxy for the pipeline slug helper."""
    from nexussy.pipeline.engine import slugify as _slugify

    return _slugify(name)
