# nexussy Implementation Checklist

<!-- PROGRESS_LOG_START -->
- Phase 0: SPEC.md read completely; root skeleton initialized; four subagents assigned from SPEC.md contracts.
- Subagent C: implemented Starlette web dashboard, `/api/*` proxy, SSE proxy, single HTML UI, fixtures, and tests.
- Subagent D: hardened dry-run installer, venv install path, complete generated config/env templates, launcher diagnostics/PID/log handling, and README operational docs.
- Subagent B: hardened TUI spec coverage for SSE payload types, fixture/live modes, client routes/auth, slash commands, reducer panels, and tests; `bun install`, `bun test`, and `bun run typecheck` pass.
- Master pass: added `SPEC_COVERAGE.md`; wired core provider path to explicit mock/fake/LiteLLM modes; added fake-Pi develop worktree integration through `/pipeline/start`; hardened TUI SSE reconnect streaming and web chat cost badge; core/TUI/web/shell smoke commands pass, but SPEC remains partial.
- Subagent D: added root-only operational smoke tests/evidence for dry-run no writes, idempotent config/env, duplicate start, stale PID cleanup, logs, and doctor diagnostics.
- Completion pass: closed `SPEC_COVERAGE.md` to 78 tested rows and 4 blocked-external live checks only; final Subagent E audit found no rejected rows.
- Guided API-key setup pass: core secrets now persist keyring-first with bounded-timeout env-file fallback, config updates persist to YAML, and provider discovery loads persisted keys; TUI adds safe provider-key status/setup/delete commands, hidden-input `--set-key`, and single-terminal provider/key/model setup with core autostart; core and TUI tests pass.
- OpenTUI pass: TUI now defaults to an `@opentui/core` chat renderer while retaining the prior Pi TUI behind `NEXUSSY_TUI_RENDERER=pi-tui`; `bun test && bun run typecheck` passes.
- OpenTUI input fix: renderer now binds explicit stdin/stdout, focuses the OpenTUI `InputRenderable` through its supported API, sizes the composer to terminal width, and repaints on input events; TUI tests and typecheck pass.
- OpenTUI layout fix: live OpenTUI input is no longer duplicated by the string-rendered composer, transcript overflow is hidden, and transcript auto-scrolls to the latest run events; TUI tests and typecheck pass.
- OpenTUI harness pass: researched OpenTUI renderer/layout/keyboard/ScrollBox/lifecycle docs and refactored the default TUI into flex regions: header, sticky-scroll transcript, wide-screen pipeline/options side rail, status strip, and focused composer; TUI tests/typecheck and OpenTUI renderer smoke pass.
- OpenTUI transcript fix: main chat now filters out artifact/checkpoint/git/worktree/worker-RPC noise, shows user prompts plus high-signal run/stage/done/error events, and keeps detailed pipeline state in the side rail; TUI tests/typecheck and renderer smoke pass.
- OpenTUI polish fix: transcript pane now flex-shrinks beside the fixed side rail to prevent text bleeding under it, and typo casual greeting `whatsg up` is handled as small talk; TUI tests/typecheck pass.
- Provider-backed idle chat pass: added core `POST /assistant/reply` using configured provider/default model without starting a pipeline, wired TUI non-project idle messages through `CoreClient.chat`, kept secrets in core, and added core/TUI regression tests; core tests and TUI tests/typecheck pass.
- Interview-first TUI pass: requests like `interview me please` enter provider-backed interview mode instead of idle chat or auto-starting the pipeline; follow-up vague app descriptions stay in interview mode until explicit `/new`; TUI tests/typecheck and core tests pass.
- TUI interaction gate pass: default composer and legacy interactive shell now keep ordinary chat in Ask mode with no provider/pipeline/inject side effects; only slash commands or pending explicit selections/confirmations enter Action mode; TUI tests/typecheck pass.
- Core interview pass: interview now uses LLM-generated question JSON, auto-synthesizes answers from project descriptions when requested, pauses manual runs for `/pipeline/{session_id}/interview/answer`, persists real multi-question artifacts, and injects interview summaries into design/devplan prompts; core tests pass.
- TUI handoff/anchor pass: added shared anchor utilities, context-window budget tracking from `cost_update`, handoff prompt generation, anchor-aware devplan/phase/handoff panels, retry-aware stage bar badges, `/handoff`, and regression tests; `bun test && bun run typecheck` passes.
<!-- PROGRESS_LOG_END -->

<!-- NEXT_TASK_GROUP_START -->
- [✅] A: core schemas, API, SSE, artifacts, SQLite, security, providers, validate/review loops, fake-Pi swarm/develop, worktrees, blockers, merge conflict lifecycle, and tests completed for deterministic implementation paths.
- [✅] B: implement TUI client, SSE parser, layout, slash commands, mock fixtures, and tests.
- [✅] C: implement Starlette web dashboard, proxy routes, SSE proxy, single HTML, fixtures, and tests.
- [✅] D: implement installer, launcher, README, AGENTS.md, config/env generation, shell tests, and root operational smoke evidence.
- [✅] F: integration evidence added across core fake provider/Pi/git/SSE, TUI client/render fixtures, web proxy/render tests, and installer/launcher smoke tests.
- [✅] G: guided TUI provider-key setup implemented with backend keyring/env-file persistence, persisted provider model selection, single-terminal core autostart, no secret-value rendering, docs, and regression tests.
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
