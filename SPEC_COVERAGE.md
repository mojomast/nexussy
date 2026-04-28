# nexussy SPEC Coverage Matrix

Status values are limited to `missing`, `partial`, `implemented-untested`, `tested`, and `blocked-external`.

| ID | Spec Section | Requirement | Owner | Implementation Files | Test Files | Status | Evidence | Notes |
|---|---|---|---|---|---|---|---|---|
| R-000 | 0 | No `ussycode`, ownership boundaries, SPEC-only contracts. | A/B/C/D | `AGENTS.md`, `handoff.md` | audit | tested | `AGENTS.md` and handoff enforce boundaries; no `ussycode` use found. | |
| R-001 | 0, 8 | Pydantic v2 schemas forbid extra fields, validate public values, UTC datetimes, JSON-safe metadata. | A | `core/nexussy/api/schemas.py` | `core/tests/test_core_contract.py` | tested | `test_schema_forbids_extra`; `python3 -m pytest -q core/tests` passed. | |
| R-002 | 0, 10, 27.4 | JSON routes and stable `ErrorResponse` route errors. | A/C | `core/nexussy/api/server.py`, `web/nexussy_web/app.py` | core/web tests | tested | `test_route_validation_error_is_normalized`; web proxy/error tests; core/web tests passed. | |
| R-003 | 0, 9, 27.4 | SSE streams use event-stream, no `[DONE]`, `done` completion. | A/B/C | core SSE, web proxy, TUI parser | core/web/tui tests | tested | Core event tests, TUI parser tests, web SSE proxy tests passed. | |
| R-004 | 0, 5, 17 | Path sanitizer and symlink escape rejection. | A | `core/nexussy/security.py`, artifact/swarms | `core/tests/test_core_contract.py` | tested | `test_security_helpers`, `test_path_and_secret_security`, lock/write tests. | |
| R-005 | 0, 14 | Pi subprocess cancellable, concurrent stdout/stderr drain, process-group isolation. | A | `core/nexussy/swarm/pi_rpc.py` | `core/tests/test_core_contract.py` | tested | Fake Pi, scrubbing, missing command, develop fake-Pi tests pass. | Live Pi check separately blocked. |
| R-006 | 0, 16 | SQLite WAL, busy timeout, bounded serialized writes and retry discipline. | A | `core/nexussy/db.py` | `core/tests/test_core_contract.py` | tested | DB pragma/table/rate-limit tests and full core tests pass. | |
| R-007 | 1, 11 | Six-stage pipeline implementation. | A | `core/nexussy/pipeline/engine.py` | core tests | tested | Mock/fake provider full-stage tests, validate/review loop tests, develop fake-Pi tests pass. | |
| R-008 | 1.1, 13 | Multi-agent swarm, roles, file claiming, dashboard events. | A/B/C | core swarm, TUI state, web dashboard | core/tui/web tests | tested | Worker spawn/task/file-lock/state/render/proxy tests passed. | |
| R-009 | 3, 4, 27.3 | Runtime architecture, localhost ports 7771/7772, process commands. | A/B/C/D | scripts and module entrypoints | smoke commands, ops tests | tested | Live core/web health and launcher smoke passed; ops tests passed. | |
| R-010 | 4, 20.2 | Launcher start/start-tui/stop/status/logs/update/doctor. | D | `nexussy.sh` | `ops_tests.sh`, smoke commands | tested | Duplicate/stale/logs/doctor ops tests plus isolated start/status/stop smoke passed. | |
| R-011 | 5.1 | Fixed paths for home/config/env/DB/run/logs/projects/worktrees/artifacts. | A/D | config, installer, launcher, pipeline | core/ops tests | tested | Config precedence, isolated install, develop artifact/worktree tests passed. | |
| R-012 | 5.1 | Project slug validation/collision behavior. | A | `schemas.py`, `pipeline/engine.py` | core tests | tested | Schema slug validation and session creation path covered by core tests. | |
| R-013 | 5.2 | Artifact paths and metadata for all pipeline artifacts. | A | artifact store, engine | core tests | tested | Pipeline artifact manifest/content, validate/review/develop reports and changed-files tests pass. | |
| R-014 | 6.1 | Config precedence and request overrides. | A | `config.py`, `providers.py` | core tests | tested | `test_config_precedence`, model override tests, pipeline fake-provider tests pass. | |
| R-015 | 6.2, 27.2 | Complete default config generated only when absent. | D | `install.sh` | `ops_tests.sh`, install smoke | tested | Dry-run/no-write and idempotent config/env tests pass. | |
| R-016 | 6.3, 27.5 | Env vars and provider key discovery. | A/D | config, providers, install/doctor | core/ops tests | tested | Provider discovery/gate tests, env template and doctor tests pass. | |
| R-017 | 7.1 | Scalar alias validation for IDs, slugs, paths, models. | A/B/C | schemas/types/parsers | core/tui/web tests | tested | Slug/model/path/schema parser tests pass. | |
| R-018 | 7.2 | Enum values match spec. | A/B/C | schemas/types/fixtures | core/tui/web tests | tested | TUI parses every SSE event type; core enum-backed route tests pass. | |
| R-019 | 8.1 | Common schemas. | A/B/C | schemas/types | core/tui tests | tested | Extra field, UTC datetime, usage/event fixture tests pass. | |
| R-020 | 8.2 | Session schemas/routes. | A/B/C | core server/schemas, TUI client | core/tui tests | tested | Session creation/list/get/delete client/server coverage included in route/client tests. | |
| R-021 | 8.3 | Pipeline schemas/routes/controls. | A/B/C | core server/schemas, clients | core/tui/web tests | tested | Pipeline start/status/control/skip/blocker tests and slash command tests pass. | |
| R-022 | 8.4 | Artifact schemas/routes. | A/B/C | artifact store/routes/UI | core/web tests | tested | Artifact manifest/content and dashboard artifact target tests pass. | |
| R-023 | 8.5 | Swarm schemas/routes/blockers/develop reports. | A/B/C | core swarm/server, TUI/web | core/tui/web tests | tested | Worker task, blocker, develop/merge report, UI state tests pass. | |
| R-024 | 8.6 | Config schemas/routes. | A/B/C/D | config/server/web/installer | core/web/ops tests | tested | Config precedence, YAML persistence, route proxy, generated config tests pass. | |
| R-025 | 10.6 | Secrets, memory, graph schemas/routes. | A/C | core server, providers, web UI | core/web tests | tested | Core secrets persistence/validation/no-echo summary tests plus web proxy/UI route tests pass. | |
| R-026 | 9.1-9.2 | SSE envelope fields and frame format. | A/B/C | engine/server/parser/proxy | core/tui/web tests | tested | Core events, TUI `parseEnvelope`, web proxy preservation tests pass. | |
| R-027 | 9.3 | SSE payload schemas for all event types. | A/B/C | schemas/types/parsers | core/tui tests | tested | TUI fixture for every Section 9 event, core emitted event tests pass. | |
| R-028 | 9.4 | SSE persistence/replay/heartbeat/bounded slow-client behavior. | A/B/C | engine/server/client/proxy | core/tui/web tests | tested | Replay tests, reconnect tests, slow-client terminal error test pass. | |
| R-029 | 10.1 | Health route and public auth exception. | A/C/D | core server/web proxy/launcher | tests/smoke | tested | Core TestClient and live curl health, web proxy health, launcher smoke pass. | |
| R-030 | 10.2 | Session route success/error semantics. | A | core server | core tests | tested | Route validation normalization and session APIs covered by core route tests. | |
| R-031 | 10.3 | Pipeline routes: start/stream/status/inject/pause/resume/skip/cancel/blocker. | A/B/C | server/clients/proxy | core/tui/web tests | tested | Control/blocker/pause/skip tests, slash command and web proxy tests pass. | |
| R-032 | 10.4 | Artifact manifest/content routes. | A/C | core routes/web UI | core/web tests | tested | Artifact route assertions and web artifact controls pass. | |
| R-033 | 10.5 | Swarm routes and worker streams. | A/B/C | core server/TUI/web | core/tui/web tests | tested | Worker spawn/assign/task/stream/proxy/state tests pass. | |
| R-034 | 10.6 | Config/secrets/memory/graph/events routes. | A/C | core server/providers/web | core/web tests | tested | Events/replay, config YAML persistence, secrets keyring/env fallback, memory/graph route/proxy tests pass. | |
| R-035 | 10.7, 19 | Web `/api/*` proxy, SSE proxy, passthrough, no business logic. | C | `web/nexussy_web/app.py` | `web/tests/test_app.py` | tested | 43 web tests passed, including method/body/query/auth/status and incremental SSE. | |
| R-036 | 11.1-11.2 | Stage order, validate correction, review return-to-plan. | A | engine | core tests | tested | `test_validate_review_correction_loops_and_controls`, max failure tests pass. | |
| R-037 | 11.2 | Interview stage entry/outputs/retry/checkpoint. | A | engine/providers/artifacts | core tests | tested | Full pipeline events/artifacts tests pass. | |
| R-038 | 11.2 | Design stage entry/outputs/retry/checkpoint. | A | engine/providers/artifacts | core tests | tested | Provider-backed fake design, validate correction, checkpoints pass. | |
| R-039 | 11.2 | Validate rule checks, LLM review, correction loop, max failure. | A | engine/providers/artifacts | core tests | tested | Validate correction and max-iteration failure tests pass. | |
| R-040 | 11.2 | Plan anchors and review feedback loop. | A | engine/artifacts | core tests | tested | Review return-to-plan and anchor artifact tests pass. | |
| R-041 | 11.2 | Review gate, return to plan, max failure. | A | engine/providers/artifacts | core tests | tested | Review loop and max-iteration failure tests pass. | |
| R-042 | 11.2, 13 | Develop stage Pi/worktree/locks/merge/reports/cleanup. | A | engine/swarm | core tests | tested | Fake-Pi develop, worker task, changed files, merge conflict tests pass. | |
| R-043 | 11.3 | Complexity scoring rubric. | A | engine | core tests | tested | Complexity exercised through pipeline phase/artifact tests. | |
| R-044 | 12.1 | Anchor constants documented and validated. | A/C/D | AGENTS, artifact store, web UI | tests/audit | tested | Safe-write anchor test, web anchor tests, AGENTS audit pass. | |
| R-045 | 12.2 | Safe writes with backup/tmp/revalidate/atomic/SSE/SQLite metadata. | A | artifact store/engine | core tests | tested | Safe write validation and artifact metadata/event pipeline tests pass. | |
| R-046 | 12.3, 21 | Token budget and three-read protocol. | D | `AGENTS.md` | audit | tested | Required sections/order present. | |
| R-047 | 13.1 | Orchestrator exists and role permissions enforced. | A | engine, roles | core tests | tested | Develop worker tests assert orchestrator; role permission tests pass. | |
| R-048 | 13.2 | Git worktree lifecycle and changed-file extraction. | A | gitops/engine | core tests | tested | Worktree lifecycle, develop integration, conflict tests pass. | |
| R-049 | 13.3 | SQLite file locks and write-lock enforcement. | A | locks/db | core tests | tested | Lock conflict and write_requires_lock tests pass. | |
| R-050 | 13.4 | Pause/resume/skip/blocker controls. | A/B/C | server/engine/clients/UI | core/tui/web tests | tested | Pause/skip/blocker events, slash commands, proxy tests pass. | |
| R-051 | 14.1 | Pi command/env/cwd and missing CLI detection. | A/D | pi_rpc/doctor | core/ops tests | tested | Fake Pi develop and missing command diagnostics pass. | Live Pi external separately blocked. |
| R-052 | 14.2 | Pi JSONL framing and unknown-event mapping. | A | pi_rpc | core tests | tested | Fake Pi JSONL/scrubbing/develop tests pass. | |
| R-053 | 14.3 | Pi safety: process group, drains, truncation, scrub, cancel/kill. | A | pi_rpc | core tests | tested | Fake Pi drain/scrub/cancel and develop tests pass. | |
| R-054 | 15.1 | LiteLLM provider execution, model selection, overrides, timeout/error/cost. | A | providers/engine | core tests | tested | Fake provider, missing-provider gate, override and cost events tested. | Live provider external separately blocked. |
| R-055 | 15.2 | Provider rate-limit persistence/blocking. | A | providers/db | core tests | tested | Rate-limit table and active blocking test pass. | |
| R-056 | 16 | Required SQLite tables/project/concurrency behavior. | A | db | core tests | tested | Required tables including blockers, WAL, busy timeout, write lock tests pass. | |
| R-057 | 17 | Security integration: sanitizer, scrubber, auth, CORS, worker cwd/write locks. | A/C/D | security/server/swarm/scripts | tests | tested | Path, symlink, scrub, auth/error, worker cwd/fake Pi tests pass. | |
| R-058 | 18.1 | TUI Pi packages/live/mock modes/three panels. | B | `tui/src/*`, package | `tui/tests/*` | tested | Pi runtime probe, provider-key status panel, render panels, `bun test`, typecheck pass. | |
| R-059 | 18.2 | TUI slash commands and export. | B | commands/client/renderer/index | TUI tests | tested | Exact endpoint/body/export escaping, safe `/secrets`/`/set-key`/`/delete-key`, and single-terminal provider setup tests pass. | |
| R-060 | 9.4, 18.2 | TUI SSE reconnect/heartbeat/done/error/auth states. | B | client/sse/state | TUI tests | tested | Reconnect Last-Event-ID, auth failure, heartbeat/done/error render tests pass. | |
| R-061 | 19 | Web required tabs and render targets. | C | web template | web tests | tested | Web tab/target fixture tests pass. | |
| R-062 | 19 | Web unavailable/auth/malformed SSE/devplan/worker/config/secrets displays. | C | web app/template | web tests | tested | 43 web tests pass for error and fixture/live render evidence. | |
| R-063 | 20.1 | Installer dependency checks/dry-run/idempotency/config/env/systemd/health/remediation. | D | `install.sh` | `ops_tests.sh`, smoke | tested | Dry-run no-write, isolated install, idempotency, syntax tests pass. | |
| R-064 | 20.2 | Launcher PID/logs/duplicate/stale/status/doctor. | D | `nexussy.sh` | `ops_tests.sh`, smoke | tested | Duplicate/stale/logs/doctor/start/status/stop evidence pass. | |
| R-065 | 21 | AGENTS.md required sections/order/content. | D | `AGENTS.md` | audit | tested | Current `AGENTS.md` matches Section 21. | |
| R-066 | 22 | Core Definition of Done. | A | core modules | core tests/smoke | tested | `python3 -m pytest -q core/tests` passes; live core health smoke passed. | |
| R-067 | 23 | TUI Definition of Done. | B | `tui/**` | TUI tests | tested | `bun test && bun run typecheck` passed with 27 tests. | |
| R-068 | 24 | Web Definition of Done. | C | `web/**` | web tests/smoke | tested | `python3 -m pytest -q web/tests` passed; web app smoke previously passed. | |
| R-069 | 25 | Installer Definition of Done. | D | root ops files | ops tests/smoke | tested | `bash -n`, dry-run, isolated install/start/status/stop, ops tests passed. | |
| R-070 | 26 | Integration test matrix. | A/B/C/D/F | test suites | core/tui/web/ops tests | tested | Full fake-provider/fake-Pi/core/web/TUI/installer evidence commands pass. | |
| R-071 | 27.1 | CLI command existence and execution. | A/B/C/D | scripts/module/package entrypoints | command suite | tested | Required commands run successfully except live external checks listed below. | |
| R-072 | 27.4 | API headers/content-types/auth/Last-Event-ID/SSE keepalive. | A/B/C | server/proxy/client | core/tui/web tests | tested | Auth/error/SSE header/reconnect/proxy tests pass. | |
| R-073 | User backlog | Live provider call with real external credentials. | A | providers/engine | fake-provider tests | blocked-external | Production path exists and fake-provider/missing-key tests pass; no real provider API key configured for live call. | True live external check only. |
| R-074 | User backlog | Live Pi CLI execution. | A/D | pi_rpc/engine/doctor | fake Pi tests, doctor | blocked-external | Production Pi subprocess path exists and fake Pi tests pass; Pi CLI is not installed. | True live external check only. |
| R-075 | User backlog | Full live multi-agent swarm orchestration with deterministic fake workers. | A | engine/swarm | core tests | tested | Orchestrator/worker/task/git/fake-Pi events tested. | |
| R-076 | User backlog | Git worktree lifecycle integrated into develop. | A | engine/gitops | core tests | tested | Develop fake-Pi and conflict lifecycle tests pass. | |
| R-077 | User backlog | Pause/resume/skip/blocker under running worker workloads. | A/B/C | server/engine/clients | core/tui/web tests | tested | Pause/skip/blocker/inject route and event evidence pass with fake workloads. | |
| R-078 | User backlog | Slow-consumer SSE behavior. | A/C | engine/server/proxy | core/web tests | tested | Slow-client terminal `sse_client_slow` and web incremental SSE tests pass. | |
| R-079 | User backlog | Live Pi subprocess path when real Pi is installed. | A/D | pi_rpc/engine/doctor | fake Pi tests | blocked-external | Fake Pi exercises production subprocess path; live Pi CLI absent. | True live external check only. |
| R-080 | User backlog | Provider/Pi/worktree/develop integration. | A/F | core engine/API/tests | core tests | tested | Public `/pipeline/start` fake provider plus fake Pi exercises provider/worktree/merge/artifacts/conflict. | |
| R-081 | Live external | Shellcheck lint command. | D | shell scripts | shell syntax/ops tests | blocked-external | `shellcheck` is not installed; `bash -n` and user-space ops tests pass. | True tool availability check only. |
