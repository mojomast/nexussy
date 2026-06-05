# nexussy Textual TUI Architecture

Framework: Python Textual. It fits the repo Python packaging style, gives first-class keyboard bindings, focus management, reactive widgets, and headless pilot tests. The implementation is separate from the existing Bun TUI so it can mature without regressing current launch behavior.

State model: `nexussy_textual.models.AppState` is the single authoritative UI state. It stores run/session ids, ordered stages, pending gate, active/selected stage, stage chat scope, transcript, workers, artifacts, routing, profiles, provider availability, interview state, diagnostics, connection state, pause/final state, and focus-return hints.

Reduction model: `nexussy_textual.state` contains pure reducers for SSE envelopes, status snapshots, provider discovery, routing edits, profile switching, gate advancement, stage chat scope, and filtered selectors. Widgets do not own pipeline business logic.

Client/actions: `client.py` wraps core HTTP/SSE routes and validates SSE frame ids/events. `actions.py` converts visible UI actions into core calls, then returns new state. Free text during a gate is routed to the completed stage unless the user explicitly advances.

Layout: header, persistent pipeline sidebar, main gate/interview/transcript/stage-control area, right inspector, bottom composer/status/footer, help screen, and command palette. Every stage is always visible and exposes visible controls plus shortcuts.
