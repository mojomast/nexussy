from __future__ import annotations

from uuid import uuid4

from nexussy.api.schemas import CheckpointPayload, StageName
from nexussy.artifacts.store import sha256_text
from nexussy.session import now_utc


STAGE_ORDER = [s.value for s in StageName]


def _stage_value(stage: StageName | str) -> str:
    value = stage.value if hasattr(stage, "value") else str(stage)
    if value not in STAGE_ORDER:
        raise ValueError(f"unknown stage: {value}")
    return value


async def save_checkpoint(db, run_id: str, stage: StageName | str, path: str, sha256: str | None = None, content: str | None = None) -> CheckpointPayload:
    """Persist a checkpoint row and return its contract payload."""
    stage_value = _stage_value(stage)
    checksum = sha256_text(content) if content is not None else (sha256 or sha256_text(stage_value))
    payload = CheckpointPayload(checkpoint_id=str(uuid4()), stage=stage_value, path=path, sha256=checksum, created_at=now_utc())
    await db.write(lambda con: con.execute(
        "INSERT INTO checkpoints VALUES(?,?,?,?,?,?)",
        (payload.checkpoint_id, run_id, payload.stage, payload.path, payload.sha256, payload.created_at.isoformat()),
    ))
    return payload


async def list_checkpoints(db, run_id: str) -> list[CheckpointPayload]:
    """List checkpoints for a run in pipeline-stage order."""
    rows = await db.read(
        "SELECT * FROM checkpoints WHERE run_id=? ORDER BY CASE stage "
        "WHEN 'interview' THEN 1 WHEN 'design' THEN 2 WHEN 'validate' THEN 3 "
        "WHEN 'plan' THEN 4 WHEN 'review' THEN 5 ELSE 6 END, created_at",
        (run_id,),
    )
    return [CheckpointPayload(checkpoint_id=r["checkpoint_id"], stage=r["stage"], path=r["path"], sha256=r["sha256"], created_at=r["created_at"]) for r in rows]


async def latest_checkpoint(db, run_id: str) -> CheckpointPayload | None:
    """Return the furthest checkpoint reached by stage order, if any."""
    checkpoints = await list_checkpoints(db, run_id)
    return checkpoints[-1] if checkpoints else None


async def resume_from_checkpoint(db, run_id: str, stage: StageName | str) -> str | None:
    """Return the checkpoint id to resume from when it is later than ``stage``."""
    requested_index = STAGE_ORDER.index(_stage_value(stage))
    checkpoint = await latest_checkpoint(db, run_id)
    if checkpoint is None:
        return None
    checkpoint_index = STAGE_ORDER.index(_stage_value(checkpoint.stage))
    return checkpoint.checkpoint_id if checkpoint_index >= requested_index else None
