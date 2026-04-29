# Full Spec Remaining Checklist

`SPEC_COVERAGE.md` was re-audited after the core review-gap and TUI handoff work. The matrix now distinguishes deterministic route/helper coverage from full contract semantics.

Current coverage summary: core Pi worker, MCP tools, web UI, session lifecycle, cost tracking, worker controls, plan task validation, TUI default-renderer contract, and the full live provider-plus-installed-Pi develop path have current evidence. Remaining partial rows are limited to install side-effect checks.

## Execution Model

Close this file through the circular loop in `CIRCULAR_DEVELOPMENT.md`. Work proceeds in cycles, not by cherry-picking rows: core runtime semantics, core contracts/providers/MCP, TUI closure, web evidence, ops evidence, then live external checks. Each cycle delegates only to the owning subagent, adds tests for new behavior, reruns the area suite, updates this file and `SPEC_COVERAGE.md`, then advances to the next cycle.

Current active cycle: none. Local/team hardening is complete, including sandboxed executor docs, deployment profiles, audit logging, `OPERATIONS.md`, rotate-key, and R-080 live provider-plus-Pi evidence.

## Highest-Priority Partial Rows

- R-063/R-069: Installer basics, dry-run, config/env idempotency, `--systemd-user` preservation, launcher status/doctor/start-tui/update wiring, and shell syntax pass, but full noninteractive install twice remains unrun to avoid package/service side effects in this environment.

## Implemented But Untested Rows

- None.

## Blocked External Rows

- None. Cycle 6 rerun after external tool installation closed R-073, R-074, R-079, and R-081 with live provider, Pi CLI/subprocess, and ShellCheck evidence without printing secret values. The local/team hardening pass closed R-080 with a full live provider plus installed Pi develop run against a throwaway repo.
