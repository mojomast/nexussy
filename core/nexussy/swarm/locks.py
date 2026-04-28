from __future__ import annotations
import asyncio
import sqlite3
from datetime import timedelta
from nexussy.api.schemas import FileLock, LockStatus, now_utc
from nexussy.security import sanitize_relative_path

async def claim_file(db, run_id: str, path: str, worker_id: str, timeout_s=120, retry_ms=250, emit=None) -> FileLock:
    loop=asyncio.get_running_loop(); rel=sanitize_relative_path(path); deadline=loop.time()+timeout_s
    waiting_emitted=False
    while True:
        now=now_utc(); exp=now+timedelta(seconds=timeout_s)
        try:
            def tx(con):
                con.execute("UPDATE file_locks SET status='expired' WHERE run_id=? AND path=? AND status='claimed' AND expires_at<?",(run_id,rel,now.isoformat()))
                con.execute("INSERT INTO file_locks VALUES(?,?,?,?,?,?)",(run_id,rel,worker_id,"claimed",now.isoformat(),exp.isoformat()))
            await db.write(tx)
            lock=FileLock(path=rel,worker_id=worker_id,run_id=run_id,status=LockStatus.claimed,claimed_at=now,expires_at=exp)
            if emit: await emit("file_claimed", lock)
            return lock
        except Exception as e:
            if not isinstance(e, sqlite3.IntegrityError):
                raise
            if emit and not waiting_emitted:
                waiting_emitted=True
                await emit("file_lock_waiting", FileLock(path=rel,worker_id=worker_id,run_id=run_id,status=LockStatus.waiting,claimed_at=now,expires_at=exp))
            if loop.time() >= deadline: raise TimeoutError("file_locked")
            await asyncio.sleep(retry_ms/1000)

async def release_file(db, run_id: str, path: str, worker_id: str) -> FileLock:
    rel=sanitize_relative_path(path); rows=await db.read("SELECT * FROM file_locks WHERE run_id=? AND path=? AND status='claimed'",(run_id,rel))
    if rows and rows[0]["worker_id"] != worker_id: raise PermissionError("forbidden")
    await db.write(lambda con: con.execute("UPDATE file_locks SET status='released' WHERE run_id=? AND path=? AND worker_id=?",(run_id,rel,worker_id)))
    return FileLock(path=rel,worker_id=worker_id,run_id=run_id,status=LockStatus.released)

async def write_requires_lock(db, run_id: str, path: str, worker_id: str) -> str:
    rel = sanitize_relative_path(path)
    now = now_utc().isoformat()
    rows = await db.read("SELECT worker_id FROM file_locks WHERE run_id=? AND path=? AND status='claimed' AND expires_at>?", (run_id, rel, now))
    if not rows:
        raise PermissionError("file_locked")
    if rows[0]["worker_id"] != worker_id:
        raise PermissionError("forbidden")
    return rel
