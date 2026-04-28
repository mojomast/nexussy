# Circular Development Loop

Use this loop to close every non-external SPEC gap without losing traceability.

## Loop Rules

1. Pick the first incomplete cycle below. Do not start later cycles until the current cycle passes its exit checks or is explicitly split.
2. Read only the required anchored status blocks first: `handoff.md` QUICK_STATUS, the matching subagent assignment, and `devplan.md` NEXT_TASK_GROUP.
3. Delegate implementation to the owning subagent only. Cross-boundary edits require a separate cycle or explicit coordinator approval.
4. Each subagent must read the relevant SPEC section, implementation files, and tests before editing.
5. Every new behavior needs a regression test. If behavior is intentionally deferred, update `SPEC_COVERAGE.md` and `FULL_SPEC_REMAINING.md` instead of pretending it is done.
6. Run the area tests before and after each cycle. At cycle close, run the full verification set listed below.
7. After each completed cycle, update `SPEC_COVERAGE.md`, `FULL_SPEC_REMAINING.md`, `devplan.md`, current `phaseNNN.md`, and `handoff.md`.

## Full Verification Set

- `python3 -m pytest -q core/tests`
- `cd tui && bun test && bun run typecheck`
- `python3 -m pytest -q web/tests`
- `bash -n install.sh nexussy.sh ops_tests.sh`
- `./install.sh --non-interactive --dry-run`
- `./ops_tests.sh`

## Cycle 1: Core Runtime Semantics

Owner: Subagent A

Rows: R-021, R-031, R-036, R-039, R-040, R-041, R-050, R-077

Scope:

- Make validate/review treat explicit `passed=false` as failure even when issue arrays are empty.
- Add provider retry loops per configured stage retry settings.
- Inject `ReviewReport.feedback_for_plan_stage` into the next plan prompt on review retry.
- Complete running-worker pause/resume semantics: pause cancels active workers, checkpoints task state, resume requeues/restarts unfinished tasks, and skip can target a task or stage with a reason.
- Ensure blockers restore the correct previous status when all blocker-severity blockers are resolved.

Exit checks:

- Core tests cover provider `passed=false`, review-feedback re-plan, worker pause/resume/requeue, task skip, and blocker restoration.
- R-021/R-031/R-036/R-039/R-040/R-041/R-050/R-077 are upgraded or narrowed accurately in `SPEC_COVERAGE.md`.

## Cycle 2: Core Contracts, Artifacts, Providers, and MCP

Owner: Subagent A

Rows: R-001, R-028, R-037, R-045, R-047, R-049, R-054, R-056, R-057, R-080, R-083

Scope:

- Tighten public scalar/path validation where feasible without breaking persisted data.
- Align slow-client SSE persistence behavior with SPEC or update SPEC/COVERAGE to document the intentional exception.
- Implement missing interview provider retry/checkpoint semantics or narrow the contract.
- Align safe-write failure/tmp/event/SQLite ordering with Section 12.2.
- Integrate role permission failures into worker tool execution and emit `tool_output success=false`.
- Emit file-lock SSE events from file lock paths.
- Complete provider retry/error/fallback evidence, including fallback `pipeline_error retryable=true`.
- Decide and implement/project-document global vs project DB behavior.
- Add MCP stdio protocol support or explicitly reclassify it out of scope in SPEC.

Exit checks:

- Core tests cover each upgraded row.
- Any intentionally narrowed contract is reflected in `SPEC.md` and `SPEC_COVERAGE.md`.

## Cycle 3: TUI Contract Closure

Owner: Subagent B

Rows: R-058, R-059, R-067, R-085, R-086

Scope:

- Decide whether OpenTUI default is the official SPEC contract or restore Pi TUI as default. Update SPEC/docs accordingly.
- Bring active composer commands into parity with SPEC: `/stage`, `/spawn`, `/export`, plus existing aliases if kept.
- Add direct tests for context-budget prompt triggers, handoff compact/patch-pause/auto-restart helpers, and blocking critical modal behavior.
- Add direct tests for DevPlan/Phase/Handoff panel parse/edit helpers and PATCH payload behavior.

Exit checks:

- `bun test && bun run typecheck` covers active runtime command paths and anchor panels.
- R-058/R-059/R-067/R-085/R-086 are upgraded or accurately narrowed.

## Cycle 4: Web Dashboard Evidence

Owner: Subagent C

Rows: R-002, R-035, R-062, R-068, R-072, R-087, R-088

Scope:

- Normalize web-originated proxy errors to the public `ErrorResponse` shape or update SPEC to allow dashboard-local errors.
- Add DOM-level tests for DevPlan anchors, unavailable/auth/malformed SSE displays, worker updates, config editor, and secrets controls.
- Add an incremental SSE proxy test that proves chunks are forwarded before stream completion.
- Add current web app startup smoke evidence.

Exit checks:

- Web tests cover proxy shape, DOM-visible dashboard behavior, and incremental SSE.
- R-002/R-035/R-062/R-068/R-072/R-087/R-088 are upgraded or accurately narrowed.

## Cycle 5: Ops and Installer Evidence

Owner: Subagent D

Rows: R-010, R-051, R-063, R-064, R-069, R-081, R-089

Scope:

- Add ops tests for `--systemd-user` unit creation and rerun preservation.
- Add launcher tests or scripted evidence for `start-tui`, `update`, exact status fields, config path, ports, PID state, and doctor Pi/provider wording.
- Run or document the closest safe substitute for full `./install.sh --non-interactive` twice; if skipped due side effects, keep row partial.
- Keep `shellcheck` blocked-external unless the tool is installed and run.

Exit checks:

- `bash -n install.sh nexussy.sh ops_tests.sh`, dry-run, and ops tests pass.
- R-010/R-051/R-063/R-064/R-069/R-089 are upgraded or accurately narrowed; R-081 remains blocked or moves to tested only with real shellcheck evidence.

## Cycle 6: Live External Closure

Owner: Coordinator with A/D

Rows: R-073, R-074, R-079, R-081

Scope:

- Run a real provider call using configured credentials.
- Run a live Pi CLI subprocess develop smoke.
- Run shellcheck if installed.

Exit checks:

- External evidence is recorded without logging secrets.
- Blocked-external rows move to tested only when real commands pass.
