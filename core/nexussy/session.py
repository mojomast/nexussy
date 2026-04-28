from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return the canonical timezone-aware UTC timestamp used by core models."""
    return datetime.now(timezone.utc)


def slugify(name: str) -> str:
    """Backwards-compatible lazy proxy for the pipeline slug helper."""
    from nexussy.pipeline.engine import slugify as _slugify

    return _slugify(name)
