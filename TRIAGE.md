## What is solid

- Core regression suite is green: `python3 -m pytest -q core/tests` passed with 89 tests and 3 existing warnings.
- `scripts/smoke_integration.sh` is executable and `bash -n scripts/smoke_integration.sh` passes.
- CI has the expected four verification jobs plus Docker gating: `.github/workflows/ci.yml` defines `core`, `tui`, `web`, `ops`, and `docker-build`, with `docker-build.needs: [core, tui, web, ops]`.
- CI uses `python3` for Python install, Ruff, core tests, web deps, and web tests in `.github/workflows/ci.yml` lines 21-28 and 63-67.
- The stage split is present: `core/nexussy/pipeline/stages/` contains `interview.py`, `design.py`, `validate.py`, `plan.py`, `review.py`, and `develop.py`.
- `core/nexussy/pipeline/engine.py` is under the target at 299 lines and still imports `nexussy.pipeline.engine` as the public orchestrator module.
- The web dashboard multi-answer flow is present: `web/nexussy_web/static/app.js` lines 160-188 renders all candidate questions into `#interview-fields`, and lines 280-293 builds and posts a full `answers` map.
- SPEC coverage currently has no `implemented-untested` or `blocked-external` rows; `FULL_SPEC_REMAINING.md` lines 19-25 list none.

## What is unproven

- R-040 remains partial in `SPEC_COVERAGE.md` line 47: plan output has anchor repair and review-feedback tests, but task owner, acceptance, and test validation remain incomplete.
- R-058 and R-067 remain partial in `SPEC_COVERAGE.md` lines 65 and 74: OpenTUI is the default runtime while SPEC still names Pi TUI/three-panel default, so the runtime contract decision is unresolved.
- R-063 and R-069 remain partial in `SPEC_COVERAGE.md` lines 70 and 76: full `./install.sh --non-interactive` twice on Ubuntu is still unrun because it has package/service side effects in this environment.
- R-075 remains partial in `SPEC_COVERAGE.md` line 82: deterministic fake workers cover orchestration paths, but full live multi-agent swarm workload-control behavior is not proven.
- `scripts/smoke_integration.sh` has syntax coverage only; the newly added script has not been run end-to-end in this session because it requires a live provider, running server, and Pi install.

## What is broken or risky

- `scripts/smoke_integration.sh` lines 48-57 parse the `done` event by reading `lines[i + 1]` as `data: ...`, but core SSE frames are `id`, `event`, `retry`, then `data` per `core/nexussy/api/server.py` line 292. The smoke script will fail or parse the wrong line for normal core SSE output.
- `scripts/smoke_integration.sh` lines 63 and 85 assert/read `changed_files`, but `ChangedFilesManifest` defines the changed-file array as `files` in `core/nexussy/api/schemas.py` lines 206-207. The smoke script will report no changed files even when the artifact is valid.
- `scripts/smoke_integration.sh` line 27 runs `$NEXUSSY_PI_COMMAND --version` unquoted. This is fragile for paths with spaces and for command strings with intended arguments; it can also split unexpectedly before the script reaches the pipeline.
- `core/nexussy/pipeline/engine.py` line 298 mutates the imported `develop.spawn_pi_worker` global before delegating to `develop.run_worker_rpc()`. This preserves an existing monkeypatch path for tests, but it is a shared module mutation and is risky under concurrent calls.
- Resolved: `FULL_SPEC_REMAINING.md` no longer says the local/team hardening pass is in progress; it now records that there is no active cycle and that hardening work is complete.

## Recommended next action

Fix and test `scripts/smoke_integration.sh` with a deterministic local harness that feeds representative core SSE frames and artifact JSON into its parsing/assertion paths. This is the single highest confidence improvement because the script is now the claimed repeatable live proof, and the static read found concrete parser/schema mismatches that would undermine that proof before any live provider or Pi behavior is evaluated.

## Effort estimate

| item | estimated hours | risk (low/med/high) |
|---|---:|---|
| Fix smoke SSE `done` parsing and add a fixture/harness test | 2 | med |
| Fix smoke changed-files assertion to use `files` and test artifact parsing | 1 | low |
| Harden `NEXUSSY_PI_COMMAND` execution semantics in the smoke script | 1 | med |
| Resolve R-058/R-067 by updating SPEC/docs or restoring Pi TUI default | 3 | med |
| Add plan task owner/acceptance/tests validation for R-040 | 4 | med |
