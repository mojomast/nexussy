# nexussy Implementation Checklist

<!-- PROGRESS_LOG_START -->
- Phase 0: SPEC.md read completely; root skeleton initialized; four subagents assigned from SPEC.md contracts.
- Subagent C: implemented Starlette web dashboard, `/api/*` proxy, SSE proxy, single HTML UI, fixtures, and tests.
- Subagent D: hardened dry-run installer, venv install path, complete generated config/env templates, launcher diagnostics/PID/log handling, and README operational docs.
- Subagent B: hardened TUI spec coverage for SSE payload types, fixture/live modes, client routes/auth, slash commands, reducer panels, and tests; `bun install`, `bun test`, and `bun run typecheck` pass.
- Master pass: added `SPEC_COVERAGE.md`; wired core provider path to explicit mock/fake/LiteLLM modes; added fake-Pi develop worktree integration through `/pipeline/start`; hardened TUI SSE reconnect streaming and web chat cost badge; core/TUI/web/shell smoke commands pass, but SPEC remains partial.
- Subagent D: added root-only operational smoke tests/evidence for dry-run no writes, idempotent config/env, duplicate start, stale PID cleanup, logs, and doctor diagnostics.
- Completion pass: closed `SPEC_COVERAGE.md` to 78 tested rows and 4 blocked-external live checks only; final Subagent E audit found no rejected rows.
<!-- PROGRESS_LOG_END -->

<!-- NEXT_TASK_GROUP_START -->
- [✅] A: core schemas, API, SSE, artifacts, SQLite, security, providers, validate/review loops, fake-Pi swarm/develop, worktrees, blockers, merge conflict lifecycle, and tests completed for deterministic implementation paths.
- [✅] B: implement TUI client, SSE parser, layout, slash commands, mock fixtures, and tests.
- [✅] C: implement Starlette web dashboard, proxy routes, SSE proxy, single HTML, fixtures, and tests.
- [✅] D: implement installer, launcher, README, AGENTS.md, config/env generation, shell tests, and root operational smoke evidence.
- [✅] F: integration evidence added across core fake provider/Pi/git/SSE, TUI client/render fixtures, web proxy/render tests, and installer/launcher smoke tests.
<!-- NEXT_TASK_GROUP_END -->

## Definitions Of Done

- Core: `python -m pytest -q core/tests` passes.
- Core: `python -m nexussy.api.server` starts on `127.0.0.1:7771`.
- Core: `/health` returns `ok=true`, `db_ok=true`, `contract_version="1.0"`.
- Core: `/pipeline/start` with mock provider creates a run and returns `RunStartResponse`.
- Core: run stream emits `run_started`, six ordered stage transitions, `checkpoint_saved`, and `done` as valid `EventEnvelope` JSON.
- Core: SSE replay with `Last-Event-ID` returns missed events in order.
- Core: validate correction and review gate limits follow the spec.
- Core: file locks prevent simultaneous writes to the same file.
- Core: git worktree lifecycle creates, commits, merges, extracts changed files, and prunes.
- Core: fake Pi JSONL subprocess fixture passes.
- Core: path sanitizer and log scrubber tests pass.
- TUI: `bun test` and `bun run typecheck` pass.
- TUI: three-panel mock rendering works without core.
- TUI: client implements required API routes used by the UI.
- TUI: SSE parser covers all Section 9 events, malformed rejection, and reconnect with `Last-Event-ID`.
- TUI: slash commands hit exact Section 18.2 endpoints.
- TUI: collapsible tool rows and agent roster updates pass tests.
- Web: `python -m pytest -q web/tests` passes.
- Web: `python -m nexussy_web.app` starts on `127.0.0.1:7772`.
- Web: `/` returns one HTML document with all required tabs.
- Web: no npm/build step required.
- Web: `/api/health` and SSE routes proxy correctly and preserve SSE fields.
- Web: DevPlan anchors are highlighted; config/secrets tabs use only API routes.
- Installer: `bash -n install.sh nexussy.sh` passes.
- Installer: `./install.sh --non-interactive` is idempotent and generates complete config/env when absent.
- Installer: launcher `start`, `status`, `stop`, and `doctor` pass smoke checks.
- Docs: `AGENTS.md` and `README.md` satisfy Section 21 and Section 25.
