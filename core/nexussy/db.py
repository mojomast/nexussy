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

import asyncio, json, pathlib, sqlite3, threading
from datetime import datetime, timezone

CURRENT_SCHEMA_VERSION = 3

STAGE_ORDER = ("interview", "design", "validate", "plan", "review", "develop")

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens", "cost_usd")

def _empty_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "provider": None, "model": None}

def _usage_from_json(raw) -> dict:
    usage = _empty_usage()
    if not raw:
        return usage
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return usage
    if not isinstance(data, dict):
        return usage
    for key in USAGE_KEYS:
        value = data.get(key, 0)
        usage[key] = float(value or 0) if key == "cost_usd" else int(value or 0)
    if not usage["total_tokens"]:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"] + usage["cache_read_tokens"] + usage["cache_write_tokens"]
    usage["provider"] = data.get("provider")
    usage["model"] = data.get("model")
    return usage

def _add_usage(target: dict, usage: dict) -> None:
    for key in USAGE_KEYS:
        target[key] += usage.get(key, 0)
    target["provider"] = usage.get("provider") or target.get("provider")
    target["model"] = usage.get("model") or target.get("model")

def _stage_sort_key(stage: str) -> tuple[int, str]:
    try:
        return (STAGE_ORDER.index(stage), stage)
    except ValueError:
        return (len(STAGE_ORDER), stage)

def _event_stage(event: dict, stage_rows: list[dict], fallback: str | None) -> str:
    created = event.get("created_at")
    for row in stage_rows:
        started = row.get("started_at")
        finished = row.get("finished_at")
        if started and created and created >= started and (not finished or created <= finished):
            return row["stage"]
    return fallback or "unknown"

def _cost_payload_usage(payload_json: str) -> dict | None:
    try:
        envelope = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict):
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    return _usage_from_json(payload)

def _transition_stage(payload_json: str) -> str | None:
    try:
        envelope = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    payload = envelope.get("payload") if isinstance(envelope, dict) else None
    if not isinstance(payload, dict):
        return None
    stage = payload.get("to_stage")
    status = payload.get("to_status")
    return stage if isinstance(stage, str) and status in (None, "running", "retrying", "paused", "passed") else None

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

def _migration_v3(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS steer_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          target TEXT NOT NULL,
          worker_id TEXT,
          message TEXT NOT NULL,
          priority TEXT NOT NULL DEFAULT 'normal',
          created_at TEXT NOT NULL,
          consumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_steer_run ON steer_events(run_id);
        """
    )

MIGRATIONS = {
    1: _migration_v1,
    2: _migration_v2,
    3: _migration_v3,
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

class _ReadPool:
    """
    Minimal thread-safe pool of SQLite read connections.
    Used only for Database.read() - writes use the existing serialized async-lock path.
    Connections are tagged PRAGMA query_only=ON so they can never accidentally write.
    """

    def __init__(self, path: pathlib.Path, busy_timeout_ms: int, maxsize: int = 3):
        self._path = path
        self._busy = busy_timeout_ms
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._pool: list = []

    def _new_conn(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self._path, timeout=self._busy / 1000, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(f"PRAGMA busy_timeout={self._busy}")
        con.execute("PRAGMA query_only=ON")
        return con

    def acquire(self):
        with self._lock:
            if self._pool:
                return self._pool.pop()
        return self._new_conn()

    def release(self, con):
        with self._lock:
            if len(self._pool) < self._maxsize:
                self._pool.append(con)
                return
        try:
            con.close()
        except Exception:
            pass

    def close_all(self):
        with self._lock:
            conns, self._pool = self._pool, []
        for con in conns:
            try:
                con.close()
            except Exception:
                pass


class Database:
    def __init__(self, path: str, busy_timeout_ms=5000, retries=5, retry_base_ms=100):
        self.path=pathlib.Path(path).expanduser(); self.busy=busy_timeout_ms; self.retries=retries; self.retry=retry_base_ms/1000; self._lock=asyncio.Lock(); self._read_pool = _ReadPool(self.path, self.busy)
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
    async def read(self, sql: str, args: tuple = ()) -> list[dict]:
        """Pooled SQLite read. Connections are reused; PRAGMA query_only prevents accidental writes."""
        def _do():
            con = self._read_pool.acquire()
            try:
                return [dict(r) for r in con.execute(sql, args).fetchall()]
            finally:
                self._read_pool.release(con)
        return await asyncio.get_event_loop().run_in_executor(None, _do)

    async def cost_analytics(self, run_id: str | None = None, *, all_runs: bool = False) -> dict:
        """Return read-only token/cost analytics derived from existing metadata.

        The helper intentionally uses only the current schema: run-level
        ``runs.usage_json``, persisted ``cost_update`` events, and
        ``stage_runs`` timestamps/status for stage attribution. It performs no
        migrations and is safe for CLI use while the API server is stopped.
        """
        if run_id and all_runs:
            raise ValueError("run_id cannot be combined with all_runs")
        if run_id:
            runs = await self.read("SELECT run_id, session_id, status, current_stage, usage_json FROM runs WHERE run_id=?", (run_id,))
            if not runs:
                raise ValueError(f"run not found: {run_id}")
        elif all_runs:
            runs = await self.read("SELECT run_id, session_id, status, current_stage, usage_json FROM runs ORDER BY started_at, run_id", ())
        else:
            runs = await self.read("SELECT run_id, session_id, status, current_stage, usage_json FROM runs ORDER BY started_at DESC, run_id DESC LIMIT 1", ())
            if not runs:
                raise ValueError("no runs found")
        result_runs = []
        totals = _empty_usage()
        for run in runs:
            item = await self._cost_analytics_for_run(run)
            result_runs.append(item)
            _add_usage(totals, item["run_total"])
        return {"runs": result_runs, "totals": totals}

    async def _cost_analytics_for_run(self, run: dict) -> dict:
        rid = run["run_id"]
        stages = await self.read("SELECT stage, status, attempt, started_at, finished_at FROM stage_runs WHERE run_id=?", (rid,))
        stages = sorted(stages, key=lambda row: _stage_sort_key(row["stage"]))
        stage_totals = {row["stage"]: _empty_usage() for row in stages}
        events = await self.read("SELECT type, payload_json, created_at FROM events WHERE run_id=? ORDER BY sequence", (rid,))
        current_stage = run.get("current_stage")
        for event in events:
            if event.get("type") == "stage_transition":
                current_stage = _transition_stage(event.get("payload_json")) or current_stage
                continue
            if event.get("type") != "cost_update":
                continue
            usage = _cost_payload_usage(event.get("payload_json"))
            if usage is None:
                continue
            stage = _event_stage(event, stages, current_stage)
            stage_totals.setdefault(stage, _empty_usage())
            _add_usage(stage_totals[stage], usage)
        run_total = _usage_from_json(run.get("usage_json"))
        if not any(stage_totals[stage]["total_tokens"] or stage_totals[stage]["cost_usd"] for stage in stage_totals):
            # Keep per-stage rows at zero when no usage events were persisted,
            # while still reporting the final run total from runs.usage_json.
            pass
        elif not run_total["total_tokens"] and not run_total["cost_usd"]:
            for usage in stage_totals.values():
                _add_usage(run_total, usage)
        stage_items = [dict({"stage": stage}, **stage_totals[stage]) for stage in sorted(stage_totals, key=_stage_sort_key)]
        return {"run_id": rid, "session_id": run.get("session_id"), "status": run.get("status"), "current_stage": run.get("current_stage"), "run_total": run_total, "stages": stage_items}

    def close(self):
        """Release all pooled read connections. Call on server shutdown."""
        self._read_pool.close_all()
