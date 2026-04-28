# nexussy Handoff

<!-- QUICK_STATUS_START -->
SPEC coverage gate passed: `SPEC_COVERAGE.md` has 78 tested rows and 4 blocked-external live checks only. Core, TUI, web, and ops deterministic implementation paths pass their test suites and required smokes; blocked checks are live provider credentials, live Pi CLI, and unavailable shellcheck.
<!-- QUICK_STATUS_END -->

<!-- HANDOFF_NOTES_START -->
- Do not use or clone `ussycode`.
- Build mock fixtures from `SPEC.md`, not from another module implementation.
- D changed only root operational files: `install.sh`, `nexussy.sh`, `ops_tests.sh`, `README.md`, `devplan.md`, `phase001.md`, and `handoff.md`.
- Shell syntax passed. Shellcheck is not installed in this environment. Full `install.sh --non-interactive` was not run to avoid package-manager side effects in `core/`, `tui/`, and `web/` during a D-only handoff.
- B changed only `tui/` implementation files plus required status updates to `devplan.md`/`handoff.md`.
- TUI imports Pi packages optionally at runtime while keeping package dependencies; deterministic renderer/state tests do not require a live core.
- C changed `web/` implementation files plus required status updates to `devplan.md`/`handoff.md`.
- `python` is not available in this environment; `python3 -m pytest -q web/tests` passes, and `PYTHONPATH=/home/mojo/projects/nexussy/web timeout 3s python3 -m nexussy_web.app` starts on `127.0.0.1:7772`.
- D hardening modified only root-owned files. Checks run: `bash -n install.sh nexussy.sh ops_tests.sh` passed; `./ops_tests.sh` passed and covers dry-run no writes, idempotent config/env, duplicate start, stale PID cleanup, logs, and doctor diagnostics; shellcheck unavailable.
- B hardening modified `tui/` implementation/tests plus required status updates to `devplan.md`/`handoff.md`; no `core/` or `web/` files were touched.
- Master pass touched core, TUI, web, root traceability/status artifacts, and `core/pyproject.toml`. Checks run: `python3 -m pytest -q core/tests`; `python3 -m pytest -q core/tests -k "develop or worktree or pi"`; `bun test && bun run typecheck`; `python3 -m pytest -q web/tests`; `bash -n install.sh nexussy.sh`; `./install.sh --non-interactive --dry-run`; isolated install/start/status/health/stop; explicit mock and fake-provider start smokes; missing-provider gate returned 503 `model_unavailable`. Shellcheck is unavailable.
- Completion checks run: `python3 -m pytest -q core/tests` (20 passed), `cd tui && bun install && bun test && bun run typecheck` (17 passed), `python3 -m pytest -q web/tests` (43 passed), `bash -n install.sh nexussy.sh ops_tests.sh`, `./install.sh --non-interactive --dry-run`, `./ops_tests.sh`, isolated install/start/status/health/stop, fake-provider production smoke, missing-provider gate, and final Subagent E audit. No sudo used.
<!-- HANDOFF_NOTES_END -->

<!-- SUBAGENT_A_ASSIGNMENT_START -->
Own `core/` only. Implement Python core contracts, schemas, API, SSE, artifacts, SQLite, security, providers, pipeline, swarm, Pi subprocess adapter, and core tests from `SPEC.md`.
<!-- SUBAGENT_A_ASSIGNMENT_END -->

<!-- SUBAGENT_B_ASSIGNMENT_START -->
Own `tui/` only. Implement TypeScript/Bun TUI contracts, client, SSE parser, three-panel UI, slash commands, fixtures, and tests from `SPEC.md`.
<!-- SUBAGENT_B_ASSIGNMENT_END -->

<!-- SUBAGENT_C_ASSIGNMENT_START -->
Own `web/` only. Implement Python Starlette dashboard, `/api/*` proxy, SSE proxy, single HTML dashboard, fixtures, and tests from `SPEC.md`.
<!-- SUBAGENT_C_ASSIGNMENT_END -->

<!-- SUBAGENT_D_ASSIGNMENT_START -->
Own root operational files only. Implement installer, launcher, README, AGENTS.md, config/env templates, and operational smoke checks from `SPEC.md`.
<!-- SUBAGENT_D_ASSIGNMENT_END -->
