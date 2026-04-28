# Phase 001

<!-- PHASE_TASKS_START -->
- Bootstrap repository skeleton and implement module contracts from `SPEC.md`.
<!-- PHASE_TASKS_END -->

<!-- PHASE_PROGRESS_START -->
- Skeleton directories and root contract artifacts initialized.
- Subagent D installer, launcher, README, config/env generation, and shell checks completed.
- Subagent B TUI client, SSE parser, state renderer, slash commands, package setup, and tests completed.
- Subagent D hardening pass added non-writing dry-run, complete Section 27.2 generated config keys, doctor diagnostics, and README production/mock-mode guidance.
- Master pass added traceability coverage, explicit provider modes, LiteLLM call path, fake-provider tests, fake Pi develop/worktree integration through the public pipeline route, TUI live SSE reconnect streaming, and web chat cost badge placement.
- Subagent D added user-space root operational smoke tests for duplicate start prevention, stale PID cleanup, dry-run no writes, idempotent config/env, logs, and doctor diagnostics.
- Completion pass closed all non-external SPEC coverage rows; remaining blocked rows are only live provider credentials, live Pi CLI, and unavailable shellcheck.
- Guided API-key setup pass added core keyring/env-file secret persistence with bounded keyring timeout fallback, config YAML persistence, provider discovery from persisted keys, TUI safe provider-key status/setup/delete commands, hidden-input setup, single-terminal provider/model selection with core autostart, docs, and regression tests.
- OpenTUI pass switched the default no-run TUI entrypoint to `@opentui/core` chat rendering, preserving the existing Pi TUI as an opt-in fallback via `NEXUSSY_TUI_RENDERER=pi-tui`; TUI tests and typecheck pass.
- OpenTUI input fix bound renderer stdin/stdout explicitly, focused the composer via `input.focus()`, resized the composer to terminal width, and repainted on input changes; TUI tests and typecheck pass.
- OpenTUI layout fix removed the duplicate inline composer from transcript rendering, hid transcript overflow, and auto-scrolled to latest events; TUI tests and typecheck pass.
- OpenTUI harness pass aligned the default renderer with OpenTUI docs: Yoga flex layout regions, focused input routing, `ScrollBoxRenderable` sticky-bottom transcript, side rail reserved for pipeline/options on wide terminals, and explicit cleanup-compatible renderer setup; TUI tests/typecheck and renderer smoke pass.
- OpenTUI transcript fix made the main chat high-signal only while preserving full event-derived pipeline state in the side rail; artifact/checkpoint/git/worktree/worker-RPC details no longer flood the default chat view.
- OpenTUI polish fix made the transcript pane shrink beside the fixed side rail and treated `whatsg up` as casual small talk rather than an invalid project prompt.
- Provider-backed idle chat pass added core `POST /assistant/reply` for configured-model replies to idle/non-project TUI messages, with TUI wiring through `CoreClient.chat` and regression coverage.
- Interview-first TUI pass added persistent provider-backed interview mode for discovery requests so vague follow-up app ideas do not auto-start the pipeline before explicit `/new`.
- TUI interaction gate pass hardened composer routing so ordinary chat stays local Ask mode and cannot start pipelines, inject context, or call providers; slash commands remain the explicit Action-mode trigger.
- Core interview pass replaced the hardcoded `Use defaults?` artifact with generated questions, auto/user answer capture, manual pause/resume API, and downstream interview context in design/devplan stages.
- TUI handoff/anchor pass added canonical anchor utilities, context-window tracking, handoff generation/trigger UI state, devplan/phase/handoff panel helpers, stage retry/checkpoint display, and tests; TUI tests/typecheck pass.
- Core review-gap pass implemented provider-backed validate/review/plan behavior, checkpoint resume and MCP tools, server/DB cleanup fixes, security/Pi/health/rate-limit hardening, and README updates; verification passed.
- SPEC coverage audit downgraded overclaimed rows, added extension/gap rows, and reopened the remaining checklist so future work targets real gaps instead of stale “all closed” status.
- Circular development setup added an H1-H6 sequential subagent loop for closing reopened SPEC rows, with Cycle 1 starting on core runtime semantics.
- Cycle 1 / Subagent A closed core runtime semantics for provider `passed=false`, provider retry loops, review-feedback re-plan, running-worker pause/resume/requeue, task skip handoff updates, and blocker previous-status restoration; core tests pass.
- Cycle 2 / Subagent A closed core contract/provider/MCP gaps for public path validation, persisted slow-client SSE diagnostics, interview retry/question checkpoints, safe-write tmp/order semantics, worker tool permission failures, file-lock events, project DB initialization, provider fallback evidence, and MCP stdio; core tests pass.
- Cycle 3 / Subagent B closed active TUI command, handoff helper, blocking modal, anchor panel, and PATCH payload test gaps; OpenTUI remains the default with Pi TUI opt-in, leaving only a SPEC/docs contract decision for R-058/R-067.
- Cycle 4 / Subagent C closed web dashboard evidence gaps: proxy-layer errors use public `ErrorResponse`, DOM execution covers errors, DevPlan anchors, worker updates, config editor, and secrets controls, incremental SSE delivery is tested before stream completion, and web startup smoke evidence was captured.
- Cycle 5 / Subagent D closed deterministic ops evidence gaps for systemd-user unit idempotency, launcher exact status fields, `start-tui`, `update`, and doctor missing-Pi/provider wording; full noninteractive install twice and shellcheck remain external/side-effect constrained.
- Cycle 6 / Coordinator reran external closure after tool installation without printing secret values: live LiteLLM/default-provider call passed with minimal response metadata, Pi CLI version/help and installed `pi --rpc` subprocess adapter startup passed under timeouts, and ShellCheck 0.11.0 passed on root scripts after lint fixes. R-073/R-074/R-079/R-081 are now tested, R-080 remains partial only for a full production provider plus live Pi develop run, and full verification passed.
- Code review fix pass closed reliability/security findings: DB read cleanup, provider secret scoping, configurable CORS, interview answer timeout, running-loop APIs, narrowed secret scrubbing, empty worker commit handling, parallel worker RPC plus serialized merge, explicit schema imports, bounded Pi frames, MCP validation, README security guidance, and AGENTS worker extension notes; core tests pass after every phase.
- Sequential review-fix subagent pass added DB indexes and write-finally cleanup, failed-run paused-state cleanup, startup serialization, exception logging/RPC depth guard, async git subprocesses, provider plaintext warnings/env caching, atomic SSE sequencing, production CORS enforcement, full MCP input schema, shell `set -euo pipefail`, and CHANGELOG; core tests passed after each subagent commit.
- README rewrite pass refreshed the root README into a concise product/operator guide covering the pipeline, architecture, setup, operations, UI surfaces, provider/Pi behavior, artifacts, security, configuration, and verification status; core tests and root shell syntax checks pass.
- Sequential repair pass closed 11 core review issues with separate commits and regression tests; full core tests passed with `python3` and an isolated mock-provider server smoke passed.
- Code review fix run closed A1-A11 plus root docs/status updates: provider keyring fallback, 429 persistence, lock/git/Pi/config/event/develop fixes, stage handler refactor, and added security regression coverage; `python3 -m pytest -q core/tests` passes.
- H/M/L code review mission closed H1-H3, M1-M4, and L1-L3 with config mutation restrictions, orchestrator path normalization, stage dispatch refactor, secret/env hardening, DB schema versioning, MCP expansion, Pi RPC event waiting, content-aware checkpoints, shared env parsing, narrowed scrubbing, and docs/status updates; final core verification passed with `python3`.
- Stub/gap wiring mission completed bundled Pi worker, real Pi RPC settings, MCP expansion, worker/pipeline controls, session lifecycle, existing repo import, usage aggregation, core `/ui`, web dashboard assets, and documentation/coverage updates; available core/web/ops/TUI checks pass.
<!-- PHASE_PROGRESS_END -->
