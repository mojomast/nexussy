# Changelog

## [Unreleased] — feature-pass-3

### Pipeline Features

- [feat:task-slicing] develop stage now parses the devplan artifact via `_slice_devplan_tasks(devplan_text)` into atomic task specs (id, title, acceptance_criteria, files_allowed) and passes one `json.dumps(task_spec)` per worker as the Pi RPC request payload.
- [feat:steering] new `nexussy_steer` MCP tool with `SteerRequest` schema persists every steering event to the `steer_events` SQLite table (schema_version bumped to 3); orchestrator-target messages enqueue on `engine.steer_queue[run_id]` and drain into `engine.steer_context[run_id]` at each stage boundary, worker-target messages forward to the existing worker inject path.
- [feat:steering-injection] plan prompts and develop task specs now prepend consumed orchestrator steering instructions; consumed messages update `steer_events.consumed_at`, and urgent steering preempts paused pipeline waits.
- [feat:devplan-sidecar] plan now saves a `devplan_tasks` JSON artifact next to `devplan.md`; develop task slicing reads the JSON sidecar first and falls back to markdown parsing when absent or invalid.
- [feat:interview-autoskip] setting `metadata.skip_interview = "true"` on `/pipeline/start` synthesizes interview answers from the project description through `engine._provider_text(StageName.interview, ...)` with `source="auto"` and skips the human pause gate.
- [feat:merge-recovery] `merge_single_worker` no longer raises immediately on merge conflict; it emits a `conflict_report` artifact listing conflicting paths, attempts `git checkout --ours` + `git add` per path, retries `git commit --no-edit`, and only raises `RuntimeError("merge conflict - auto-resolution failed")` if the second commit fails.

## [Unreleased] — gap-sprint-2

### Local-Team Hardening

- [review-response] fix: web dashboard now submits all interview answers in one batch.
- [review-response] fix: CI matrix expanded — TUI, web, ops jobs added, `python3` throughout.
- [review-response] refactor: `engine.py` split into `pipeline/helpers.py` + `pipeline/stages/*`.
- [review-response] feat: `scripts/smoke_integration.sh` — repeatable live integration smoke.
- [smoke-hardening] fix: SSE done-frame parser in smoke script handles core's multiline frame format.
- [smoke-hardening] fix: `changed_files` field name verified and corrected to `files` in the smoke script.
- [smoke-hardening] fix: `PI_COMMAND` space/args handling hardened in script and core.
- [smoke-hardening] fix: engine compat wrapper no longer mutates `spawn_pi_worker` globally.
- [smoke-hardening] docs: `FULL_SPEC_REMAINING.md` stale status text cleared.
- [post-review-hardening] fix: `_command_parts()` resolves executable paths before spawning Pi workers.
- [post-review-hardening] fix: develop stage handler forwards injected `spawn_fn` test doubles.
- [post-review-hardening] docs: clarified why `pi` command args are overridden with `--mode rpc`.
- [production-hardening] test: secret delete now has provider-cache invalidation coverage alongside secret update coverage.
- [production-hardening] fix: plan artifacts repair missing task owner, acceptance criteria, and tests to close R-040.
- [production-hardening] fix: TUI no-run mode now defaults to OpenTUI, with Pi TUI available through `NEXUSSY_TUI_RENDERER=pi-tui`.
- [production-hardening] docs: SPEC, README, OPERATIONS, coverage, and triage artifacts now reflect the OpenTUI default and remaining install-side-effect evidence only.
- [2026-04-29] feat: full spec coverage achieved - install idempotency and live swarm proof (R-063, R-069, R-075).
- [local-team-hardening] Documented the supported `pi.command` / `NEXUSSY_PI_COMMAND` sandboxed executor pattern for trusted LAN/VPN use, clarified that bundled `nexussy-pi` is local-dev only and not a security boundary, and added a launcher doctor warning when bundled Pi is selected with a non-localhost bind.
- [local-team-hardening] Added `NEXUSSY_PROFILE=dev|trusted-lan`; `trusted-lan` enables API-key auth, rejects wildcard CORS, requires an explicit Pi command, warns on bundled `nexussy-pi`, and moves default service logs under `~/.nexussy/logs/`.
- [local-team-hardening] Added local append-only `~/.nexussy/audit.log` entries for pipeline lifecycle, config changes, secret add/delete, worker spawn, and auth failures, plus `./nexussy.sh logs --audit`.
- [local-team-hardening] Added `OPERATIONS.md` with SQLite snapshot/restore, schema-version, migration, backup-frequency, and audit-log guidance for solo and trusted-team operators.
- [local-team-hardening] Added `./nexussy.sh rotate-key` for local API-key rotation and wired failed API-key attempts into the existing SQLite `rate_limits` table.
- [local-team-hardening] Updated the real Pi adapter for Pi 0.70.6 `--mode rpc` / `prompt` frames and closed R-080 with a full live configured-provider plus installed-Pi develop pipeline smoke.

### Fixed

- **Worker sandbox**: replaced bypassable bash denylist with stripped-env subprocess + 64KB output cap
- **Database**: SQLite read connection pool (3 connections, query_only) eliminates per-read connection overhead

### Added

- **Web UI**: Full pipeline control surface (stage stepper, workers table, blockers, interview form, pause/resume/cancel, API key auth)

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
- Hardened root operations: launcher health-wait failures now terminate the just-started service and clear its PID, foreground TUI runs get lifecycle PID/log handling, systemd user units reject unsupported unescaped paths, and ops tests keep temporary outputs under their private temp root.

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
