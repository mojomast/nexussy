# Full Spec Remaining Checklist

`SPEC_COVERAGE.md` was re-audited after the core review-gap and TUI handoff work. The matrix now distinguishes deterministic route/helper coverage from full contract semantics.

Current coverage summary: 80 tested rows, 10 partial rows, 0 implemented-untested rows, and 0 blocked-external rows.

## Execution Model

Close this file through the circular loop in `CIRCULAR_DEVELOPMENT.md`. Work proceeds in cycles, not by cherry-picking rows: core runtime semantics, core contracts/providers/MCP, TUI closure, web evidence, ops evidence, then live external checks. Each cycle delegates only to the owning subagent, adds tests for new behavior, reruns the area suite, updates this file and `SPEC_COVERAGE.md`, then advances to the next cycle.

Current active cycle: Cycle 6 complete; remaining gaps are partial implementation/evidence decisions, not blocked external tooling.

## Highest-Priority Partial Rows

- R-040: Provider plan output, anchor repair, and review feedback injection are tested, but plan task owner/acceptance/tests validation remains incomplete.
- R-054/R-080: Fake provider/fake Pi integration, provider retry, fallback `pipeline_error retryable=true`, a live LiteLLM provider call, and live Pi subprocess startup are tested separately, but one full production provider plus live Pi develop run remains unproven because it may invoke agent/model behavior and file changes beyond safe smoke scope.
- R-058/R-067: TUI tests pass with active composer commands and handoff/panel coverage, but SPEC/runtime alignment is incomplete. Cycle 3 kept OpenTUI as the default runtime and Pi TUI as opt-in; a SPEC/docs decision is needed to make that official or restore Pi TUI as default.
- R-063/R-069: Installer basics, dry-run, config/env idempotency, `--systemd-user` preservation, launcher status/doctor/start-tui/update wiring, and shell syntax pass, but full noninteractive install twice remains unrun to avoid package/service side effects in this environment.

## Implemented But Untested Rows

- None.

## Blocked External Rows

- None. Cycle 6 rerun after external tool installation closed R-073, R-074, R-079, and R-081 with live provider, Pi CLI/subprocess, and ShellCheck evidence without printing secret values.
