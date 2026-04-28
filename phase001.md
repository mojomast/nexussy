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
<!-- PHASE_PROGRESS_END -->
