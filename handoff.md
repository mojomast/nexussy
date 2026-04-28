# nexussy Handoff

<!-- QUICK_STATUS_START -->
SPEC coverage gate passed: `SPEC_COVERAGE.md` has 78 tested rows and 4 blocked-external live checks only. Core, TUI, web, and ops deterministic implementation paths pass their test suites and required smokes; blocked checks are live provider credentials, live Pi CLI, and unavailable shellcheck.
Guided provider-key setup added: core `/secrets` persists keyring-first with env-file fallback, bounded keyring timeouts to avoid onboarding hangs, `/config` updates persist to YAML, and provider discovery reads persisted keys; TUI supports `/secrets`, `/set-key NAME` hidden-input guidance, `/delete-key NAME`, `bun run start -- --set-key NAME`, `bun run start -- --setup`, and `bun run start -- --setup-openrouter` for single-terminal provider key/model setup with core autostart and without rendering secret values.
OpenTUI default added: TUI no-run interactive mode now uses `@opentui/core` chat rendering; set `NEXUSSY_TUI_RENDERER=pi-tui` to use the previous Pi TUI. TUI `bun test && bun run typecheck` passes.
OpenTUI input focus fix added: composer binds stdin/stdout explicitly, uses `input.focus()`, resizes to terminal width, and repaints as input changes; TUI tests/typecheck pass.
OpenTUI layout fix added: transcript no longer includes the string-rendered composer, overflow is hidden, and the transcript scrolls to latest events so the live input box remains usable.
OpenTUI harness refactor added: renderer now follows OpenTUI layout/input guidance with header, sticky-scroll transcript, wide-screen pipeline/options side rail, status strip, and focused composer regions; tests/typecheck and renderer smoke pass.
OpenTUI transcript fix added: default chat suppresses artifact/checkpoint/git/worktree/worker-RPC noise and renders only user prompts plus high-signal run/stage/done/error activity; side rail retains pipeline/workers/options context.
OpenTUI polish fix added: transcript flex-shrinks beside the fixed side rail to avoid overlap, and casual typo greeting `whatsg up` is classified as small talk.
Provider-backed idle chat added: core `POST /assistant/reply` uses the configured provider/default model for non-project TUI messages without starting a pipeline; TUI calls it through `CoreClient.chat`, so provider secrets remain core-owned.
Interview-first TUI mode added: `interview me please` and similar discovery intents use provider-backed chat to ask clarifying questions and keep follow-ups out of pipeline start until `/new` is explicit.
TUI interaction gate added: ordinary composer and legacy shell text stays in local Ask mode with no provider/pipeline/inject side effects; Action mode requires slash commands or pending explicit selection/confirmation.
Core interview stage added: generated question output is parsed into `InterviewArtifact`, auto mode synthesizes answers from descriptions, manual mode pauses until `/pipeline/{session_id}/interview/answer`, and design/devplan prompts include interview context.
TUI handoff/anchor pass added: shared anchor parsing/writing, context-budget tracking, handoff modal trigger state, handoff document generation/auto-restart request helpers, anchor-aware devplan/phase/handoff panels, retry/checkpoint-aware stage bar, `/handoff`, and regression tests. TUI `bun test && bun run typecheck` passes.
Core review-gap fixes added: validate/review/plan now consume provider output, report-driven retry loops work, checkpoints resume later stages, MCP tools expose start/status, session delete/cancel/interview cleanup paths are hardened, server initialization moved to startup, logs scrub more token forms, rate limits emit `Retry-After`, Pi health/termination are safer, and README/status artifacts were updated.
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
- Guided key setup checks run: `python3 -m pytest -q core/tests` (25 passed) and `cd tui && bun test && bun run typecheck` (27 passed). Piped setup reproduction completed. No secret values are returned by core summaries or rendered by TUI provider-key panels.
- Added root `launch_verify.sh` helper to start core/web, verify health endpoints, report provider-key count, and print TUI launch instructions.
- OpenTUI default pass changed only `tui/` code plus required status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (38 passed) and OpenTUI app module import smoke passed.
- OpenTUI input fix changed only `tui/src/opentui-app.ts` plus required status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (38 passed).
- OpenTUI layout fix changed only `tui/src/opentui-app.ts` plus required status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (38 passed).
- OpenTUI harness refactor changed only `tui/src/opentui-app.ts` plus required status artifacts. Research used OpenTUI renderer, layout, keyboard, input, ScrollBox, and lifecycle docs. Checks run: `cd tui && bun test && bun run typecheck` (38 passed) and OpenTUI renderer smoke passed.
- OpenTUI transcript fix changed only `tui/src/opentui-app.ts` plus required status artifacts after inspecting `/tmp/nexussy-tui.log` and `/tmp/nexussy-core.log`. Checks run: `cd tui && bun test && bun run typecheck` (38 passed) and OpenTUI renderer smoke passed.
- OpenTUI polish fix changed `tui/src/opentui-app.ts` and `tui/src/ui/Composer.ts` plus required status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (38 passed).
- Provider-backed idle chat changed `core/nexussy/api/schemas.py`, `core/nexussy/api/server.py`, `core/nexussy/providers.py`, TUI client/composer/types/tests, and status artifacts after user approved a core chat endpoint. Checks run: `python3 -m pytest -q core/tests` (28 passed) and `cd tui && bun test && bun run typecheck` (38 passed).
- Interview-first TUI mode changed `tui/src/ui/Composer.ts`, `tui/src/ui/types.ts`, `tui/src/opentui-app.ts`, and `tui/tests/chat-ux.test.ts` plus status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (39 passed) and `python3 -m pytest -q core/tests` (28 passed).
- TUI interaction gate changed `tui/src/ui/Composer.ts`, `tui/src/ui/types.ts`, `tui/src/index.ts`, `tui/src/ui/Onboarding.ts`, and TUI tests plus status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (40 passed).
- Core interview pass changed `core/nexussy/pipeline/engine.py`, `core/nexussy/api/schemas.py`, `core/nexussy/api/server.py`, `core/tests/test_core_contract.py`, and `core/tests/test_interview.py` plus status artifacts. Checks run: `python3 -m pytest -q core/tests` (33 passed).
- TUI handoff/anchor pass changed only `tui/` implementation/tests plus required status artifacts. Checks run: `cd tui && bun test && bun run typecheck` (58 passed).
- Core review-gap pass changed core pipeline/server/checkpoint/MCP/session/security/Pi code, installer systemd idempotency, README, and status artifacts. Checks run: `python3 -m pytest -q core/tests` (44 passed), `cd tui && bun test` (58 passed), and `bash -n install.sh nexussy.sh` passed.
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
