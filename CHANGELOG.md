# Changelog

## [Unreleased] — 2026-04-28

### Fixed

- **P0** Remove unused `aiosqlite` dependency from `pyproject.toml`
- **P0** Fix `_startup_lock` initialization race condition on cold start in `server.py`
- **P0** `local_pi_worker`: agent failures now propagate as JSON-RPC errors instead of silent `status=ok`
- **P0** Add multi-worker deployment guard warning; enforce `--workers 1` in Dockerfile
- **P1** `LazyCORSMiddleware` now caches the resolved middleware instance after first request
- **P1** Log warning when auth is disabled on a non-localhost bind address
- **P1** Add hourly TTL cleanup for expired `rate_limits` rows in database
- **P1** Add `conftest.py` with temp-dir isolation to prevent tests from touching `~/.nexussy`
- **P1** Orphaned `running` runs are automatically marked `failed` on engine startup with recovery instructions
- **P1** Document restart recovery in `AGENTS.md`

### Added

- Web UI: Full pipeline control surface replacing the minimal stub (stage stepper, workers, blockers, interview form, controls)
- `Dockerfile` for containerized deployment (enforces `--workers 1`)
- `.github/workflows/ci.yml` — automated lint, test, and Docker build on push/PR
- `Database.cleanup_expired()` method for rate limit housekeeping
- `Engine.restore_interview_state()` for post-restart run recovery

## [Unreleased]

### Fixed

- Wired pipeline and worker inject/stop controls, worker stream run-id resolution, session status transitions, existing repository import, and per-run token usage aggregation.
- Added bundled `nexussy-pi` Pi-compatible worker shim, real Pi CLI `--rpc-mode` settings, and local Pi JSON-RPC smoke coverage.
- Expanded MCP with interview, inject, worker spawn/assign/list, session, artifact, pause, resume, and cancel tools.
- Added core `/ui` static dashboard route and refreshed the standalone web dashboard with session polling, status, SSE logs, and interview answer submission.
- Restricted `PUT /config` to safe mutable keys and rejected auth, database, home, project, and non-whitelisted config changes.
- Normalized orchestrator file paths before role allowlist checks and tightened phase path matching.
- Stopped keyring-backed secret writes from copying secret values into `os.environ`.
- Added SQLite schema version tracking and migration recording.
- Expanded MCP tools for pause, resume, cancel, artifacts, and sessions; fixed JSON-RPC parse, invalid request, unknown method, and execution error codes.
- Ensured Pi RPC waits for responses with `asyncio.Event` and raises `RuntimeError` when worker stdin is closed.
- Made checkpoints hash supplied content when available.
- Reused the provider env-file parser from config loading.
- Tightened secret scrubbing to avoid non-secret git/hash false positives while retaining API key, `sk-`, and PEM redaction.

### Refactored

- Split pipeline stage artifact generation into per-stage `Engine` handler methods behind a thin dispatcher.

### Fixed - 2026-04-28

- `providers.py`: keyring sentinel fallback now warns and stores to file when keyring writes fail or time out.
- `providers.py`: `complete()` now auto-persists provider rate-limit 429 errors to the DB when a DB handle is supplied.
- `swarm/locks.py`: lock contention handling is narrowed to `sqlite3.IntegrityError`; other DB errors propagate.
- `swarm/gitops.py`: renamed-file diff parsing now uses the new path for `R` status lines.
- `pipeline/engine.py`: event persistence now uses `RETURNING` for sequence assignment.
- `pipeline/engine.py`: mock develop-stage orchestrator worker IDs are unique per run.
- `swarm/pi_rpc.py`: stdin availability now raises `RuntimeError`, and response waiting uses `asyncio.Event` instead of polling.
- `config.py`: `_set()` now coerces negative integers and floats as numeric values.
- `pipeline/engine.py`: `_artifacts_for_stage()` dispatches to per-stage handler methods.
- `security.py`: added unit coverage for log scrubbing and path sanitization edge cases.

### Critical

- Fixed SQLite connection cleanup in write paths and added indexes for run, event, artifact, worker task, blocker, checkpoint, and memory lookups.
- Cleared paused run state on interview answer timeout and failed pipeline runs.
- Serialized core server startup initialization with an asyncio lock to prevent global state races.

### Major

- Added pipeline failure logging and worker RPC resume depth guarding.
- Converted git worktree operations to timeout-bounded async subprocess calls.
- Warn when provider secrets fall back to plaintext env-file storage and reuse cached provider env values during completion calls.
- Made SSE event sequencing atomic at insert time.
- Enforced production CORS safety and expanded the MCP start-pipeline input schema.

### Minor

- Hardened root shell scripts with `set -euo pipefail` and safer variable handling.
- Documented production security settings, worker orchestration extension points, interview timeout cleanup, and review-fix status.
