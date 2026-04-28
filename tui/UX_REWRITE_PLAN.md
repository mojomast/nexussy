# TUI UX Rewrite Plan

## Current Problems

- Default launch presents a static three-column dashboard (`Agents | Stream | DevPlan`) instead of a coding-agent transcript.
- Natural language input previously behaved like an invalid slash command or started runs without readable assistant-style narration.
- Event rendering is coupled to monitoring panels, so stage/tool/worker/file activity is not shaped as chronological transcript items.
- The dashboard is the first impression instead of an optional inspection view.
- Missing dependency failures render as raw stream errors instead of actionable recovery guidance.
- `@file` references and slash-command discovery are not part of the primary composer UX.

## Target Interaction Model

- Default mode is Claude Code/OpenCode-style chat: header, transcript scrollback, compact status strip, and `nexussy ›` composer.
- Plain text starts a new run when idle and injects context when a run is active.
- Slash commands are keyboard-first and open compact overlays for status, plan, artifacts, workers, secrets, doctor, and help.
- `/dashboard` toggles the old monitoring panels as a secondary mode; `/chat` returns to transcript mode.
- SSE events are reduced into typed transcript display items rather than rendered directly from raw events.
- Heartbeats update connection metadata only and do not render unless debug mode is later added.
- File references use local project-root-bounded autocomplete and insert literal `@path` text for core compatibility.

## Files To Modify

- `tui/src/index.ts`: keep launch/setup flow, route default UI into chat TUI.
- `tui/src/pi-app.ts`: replace default dashboard component with chat-first Pi TUI app.
- `tui/src/commands.ts`: expand command handling and overlay state behavior.
- `tui/src/renderer.ts`: keep dashboard rendering as optional secondary/export path.
- `tui/src/ui/*`: add separated chat UI components and transcript/composer/file-ref helpers.
- `tui/src/lib/*`: keep anchor parsing, context-budget calculation, and handoff generation as pure testable helpers.
- `tui/src/panels/*`: keep artifact-specific devplan, handoff, and phase anchor handling out of renderer code.
- `tui/src/components/*`: keep reusable status/handoff display helpers separate from state reduction.
- `tui/tests/*`: add transcript, command, overlay, slash, file-ref, and default-shape tests.

## Tests To Add

- Default render is chat mode and does not contain permanent `Agents | Stream | DevPlan` columns.
- `/dashboard` switches to dashboard; `/chat` returns to transcript.
- Plain text idle starts a run; plain text during active run injects context.
- `/new`, `/pause`, `/resume-run`, `/skip`, `/inject`, `/workers`, `/plan`, `/artifacts`, `/doctor`, `/secrets` behavior.
- Heartbeats do not create transcript rows.
- Stage/tool/worker/file/artifact/done events become compact transcript rows/cards.
- Missing Pi CLI errors render with next actions.
- `@file` autocomplete opens, inserts references, and rejects path escape.
- Existing SSE reconnect/malformed error coverage remains passing.

## API Gaps / TODOs

- `/doctor` has no core route. TUI will show a local diagnostic fallback from known health/config/provider state and mark this as a TUI-side fallback, not a fake core success.
- `/plan` needs the latest artifact content when a session exists; initial implementation shows known devplan/artifact summaries and falls back gracefully if no session/run exists.
- Run-scoped compact and session artifact patch endpoints are represented in the client for handoff workflows; live behavior depends on matching core route availability.

## Acceptance Checklist

- [x] `cd tui && bun install && bun test && bun run typecheck` passes.
- [x] Default TUI render is transcript-first chat mode.
- [x] Default TUI render does not resemble the bordered three-panel screenshot.
- [x] Dashboard exists only after `/dashboard`.
- [x] Slash commands and natural language submit behavior are tested.
- [x] `@file` references are tested and project-root bounded.
- [x] Missing Pi CLI/LiteLLM errors render as actionable blocks.
- [x] Heartbeats do not spam transcript.
- [x] TUI uses only `tui/src/client.ts` to communicate with core.
- [x] `/handoff` opens a local handoff overlay and records the user-command trigger.
- [x] Context-budget state is recomputed from `cost_update` usage and rendered in the status strip.
- [x] Devplan, phase, and handoff helpers update documents through shared anchor utilities.
- [x] Validate-to-design and review-to-plan retries render as retrying rather than failed.
