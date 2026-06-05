# Migration Note

The existing Bun/OpenTUI remains intact. This package introduces a new Textual frontend focused on long-running pipeline control rather than chat-first operation.

Key UX differences:

- All stages are always visible in a persistent sidebar with status, activity, routing, fallback, gate, pause/retry/worker hints.
- Stage controls are visible buttons with keyboard equivalents, not primarily slash-command driven.
- Stage chat is a scoped mode with filtered transcript and scoped composer injection.
- Gates are explicit cards with Advance, Stay Paused, Stage Chat, Artifacts, and Workers paths.
- Routing/settings are a dedicated matrix using configured providers as normal options and showing missing providers as disabled.
- Interview is a first-class wizard panel with progress, suggestions, Enter-to-accept, and waiting state.
- State is centralized in typed reducers so screens subscribe to derived state rather than duplicating pipeline logic.

Launcher integration is intentionally separate from this first package slice. Once validated, `nexussy.sh` can add a `start-textual-tui` command or switch the default after user acceptance.
