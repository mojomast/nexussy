from __future__ import annotations
"""SQLite helpers with serialized writes and WAL-friendly unlocked reads.

Writes use a process-local async lock plus `BEGIN IMMEDIATE` to avoid concurrent
writer conflicts. Reads intentionally do not take that lock; callers that need
strict read-after-write visibility must await the preceding write first.

Migration pattern: keep `SCHEMA` idempotent for the current table shape, then
run numbered migration functions in ascending order and append one row per
applied version to `schema_version`. New installs replay the same migrations as
upgrades, so each migration must be safe after `CREATE TABLE IF NOT EXISTS`.
"""

import asyncio, pathlib, sqlite3
from datetime import datetime, timezone

CURRENT_SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY, project_slug TEXT UNIQUE, project_name TEXT, status TEXT, created_at TEXT, updated_at TEXT, detail_json TEXT);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, session_id TEXT, status TEXT, current_stage TEXT, started_at TEXT, finished_at TEXT, usage_json TEXT);
CREATE TABLE IF NOT EXISTS stage_runs(run_id TEXT, stage TEXT, status TEXT, attempt INTEGER, started_at TEXT, finished_at TEXT, error_json TEXT, PRIMARY KEY(run_id,stage));
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, run_id TEXT, sequence INTEGER, type TEXT, payload_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS artifacts(run_id TEXT, kind TEXT, path TEXT, sha256 TEXT, bytes INTEGER, updated_at TEXT, content_text TEXT, phase_number INTEGER, PRIMARY KEY(run_id,kind,path));
CREATE TABLE IF NOT EXISTS checkpoints(checkpoint_id TEXT PRIMARY KEY, run_id TEXT, stage TEXT, path TEXT, sha256 TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS workers(worker_id TEXT PRIMARY KEY, run_id TEXT, role TEXT, status TEXT, task_id TEXT, worktree_path TEXT, branch_name TEXT, pid INTEGER, usage_json TEXT, last_error_json TEXT, worker_json TEXT);
CREATE TABLE IF NOT EXISTS worker_tasks(task_id TEXT PRIMARY KEY, run_id TEXT, worker_id TEXT, phase_number INTEGER, title TEXT, status TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS blockers(blocker_id TEXT PRIMARY KEY, run_id TEXT, worker_id TEXT, stage TEXT, severity TEXT, message TEXT, resolved INTEGER, created_at TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS file_locks(run_id TEXT, path TEXT, worker_id TEXT, status TEXT, claimed_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS rate_limits(provider TEXT, model TEXT, reset_at TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS memory_entries(memory_id TEXT PRIMARY KEY, session_id TEXT, key TEXT, value TEXT, tags_json TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS secrets(name TEXT PRIMARY KEY, source TEXT, configured INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_stage_runs_run ON stage_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id, kind);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
CREATE INDEX IF NOT EXISTS idx_worker_tasks_run ON worker_tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_blockers_run ON blockers(run_id, resolved);
CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id);
CREATE INDEX IF NOT EXISTS idx_memory_entries_session ON memory_entries(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_locks_claimed ON file_locks(run_id, path) WHERE status='claimed';
"""

def _migrate_file_locks_schema(con):
    row=con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='file_locks'").fetchone()
    if not row or "UNIQUE(run_id,path,status)" not in (row[0] or "").replace(" ", ""):
        return
    con.execute("ALTER TABLE file_locks RENAME TO file_locks_old")
    con.execute("CREATE TABLE file_locks(run_id TEXT, path TEXT, worker_id TEXT, status TEXT, claimed_at TEXT, expires_at TEXT)")
    con.execute("INSERT INTO file_locks SELECT run_id, path, worker_id, status, claimed_at, expires_at FROM file_locks_old")
    con.execute("DROP TABLE file_locks_old")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_locks_claimed ON file_locks(run_id, path) WHERE status='claimed'")

def _migration_v1(con):
    _migrate_file_locks_schema(con)

def _migration_v2(con):
    # Version 2 introduces explicit schema_version tracking; the table itself is
    # created by SCHEMA so this migration only records that tracking is active.
    return None

MIGRATIONS = {
    1: _migration_v1,
    2: _migration_v2,
}

def _apply_schema_migrations(con):
    row = con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    current = int(row[0] or 0) if row else 0
    for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(f"missing schema migration {version}")
        migration(con)
        con.execute(
            "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(?, ?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )

class Database:
    def __init__(self, path: str, busy_timeout_ms=5000, retries=5, retry_base_ms=100):
        self.path=pathlib.Path(path).expanduser(); self.busy=busy_timeout_ms; self.retries=retries; self.retry=retry_base_ms/1000; self._lock=asyncio.Lock()
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con=sqlite3.connect(self.path, timeout=self.busy/1000, check_same_thread=False)
        con.row_factory=sqlite3.Row; con.execute("PRAGMA journal_mode=WAL"); con.execute(f"PRAGMA busy_timeout={self.busy}"); con.execute("PRAGMA foreign_keys=ON")
        return con
    async def init(self):
        def tx(con):
            con.executescript(SCHEMA)
            _apply_schema_migrations(con)
        await self.write(tx)
    async def init_project(self, project_root: str, relative_path: str = ".nexussy/state.db"):
        project_db = Database(str(pathlib.Path(project_root).expanduser() / relative_path), self.busy, self.retries, int(self.retry * 1000))
        await project_db.init()
        return project_db.path
    async def cleanup_expired(self) -> int:
        """Delete expired rate_limit rows. Returns number of rows deleted."""
        now = datetime.now(timezone.utc).isoformat()
        result = {"deleted": 0}
        def tx(con):
            cur = con.execute("DELETE FROM rate_limits WHERE reset_at < ?", (now,))
            result["deleted"] = cur.rowcount
        await self.write(tx)
        return result["deleted"]
    async def write(self, fn):
        """Run a serialized SQLite write transaction with bounded retries."""
        async with self._lock:
            last=None
            for i in range(self.retries):
                con=None
                try:
                    con=self.connect(); con.execute("BEGIN IMMEDIATE"); res=fn(con); con.commit(); return res
                except sqlite3.IntegrityError:
                    try: con.rollback()
                    except Exception: pass
                    raise
                except sqlite3.OperationalError as e:
                    last=e
                    try: con.rollback()
                    except Exception: pass
                    await asyncio.sleep(self.retry*(2**i))
                finally:
                    try:
                        if con is not None: con.close()
                    except Exception: pass
            raise last
    async def read(self, sql, args=()):
        """Run an unlocked SQLite read and always close the connection."""
        con=self.connect()
        try:
            rows=[dict(r) for r in con.execute(sql,args).fetchall()]
        finally:
            con.close()
        return rows
