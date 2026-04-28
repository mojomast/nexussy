# Changelog

## [Unreleased]

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
