## What is solid

- Resolved: smoke SSE parsing now reads the next non-empty `data:` line after `event: done`, and `scripts/test_smoke_parser.sh` proves core-style multiline frames locally.
- Resolved: the smoke script now uses the verified `ChangedFilesManifest.files` field instead of `changed_files`.
- Resolved: `NEXUSSY_PI_COMMAND` handling now preserves executable paths with spaces, supports command strings with args, and posts `pi_command` plus `pi_args` separately.
- Resolved: the engine compatibility wrapper no longer mutates `develop.spawn_pi_worker` globally; tests pass `spawn_fn` explicitly.
- Resolved: secret set/delete routes invalidate the provider env cache, and core tests prove subsequent provider calls see updated and removed keys.
- Resolved: R-040 plan task validation repairs missing owner, acceptance criteria, and tests while preserving provider plan content.
- Resolved: R-058/R-067 now define OpenTUI as the default TUI renderer with `NEXUSSY_TUI_RENDERER=pi-tui` as the Pi TUI opt-in path.
- Resolved: `FULL_SPEC_REMAINING.md` stale local/team hardening “in progress” text is cleared.
- Core regression suite is green: `python3 -m pytest -q core/tests` passed with 91 tests and 3 existing warnings.
- TUI regression suite is green: `bun test && bun run typecheck` passed with 67 tests.
- Web regression suite is green: `python3 -m pytest -q web/tests` passed with 52 tests.
- Root operations checks are green: shell syntax, `./ops_tests.sh`, and `./install.sh --non-interactive --dry-run` pass.
- `scripts/smoke_integration.sh` syntax and parser harness pass: `bash -n scripts/smoke_integration.sh`; `bash scripts/test_smoke_parser.sh`.
- CI has the expected four verification jobs plus Docker gating: `.github/workflows/ci.yml` defines `core`, `tui`, `web`, `ops`, and `docker-build`, with `docker-build.needs: [core, tui, web, ops]`.
- CI uses `python3` for Python install, Ruff, core tests, web deps, and web tests in `.github/workflows/ci.yml` lines 21-28 and 63-67.
- The stage split is present: `core/nexussy/pipeline/stages/` contains `interview.py`, `design.py`, `validate.py`, `plan.py`, `review.py`, and `develop.py`.
- `core/nexussy/pipeline/engine.py` is under the target at 299 lines and still imports `nexussy.pipeline.engine` as the public orchestrator module.
- The web dashboard multi-answer flow is present: `web/nexussy_web/static/app.js` lines 160-188 renders all candidate questions into `#interview-fields`, and lines 280-293 builds and posts a full `answers` map.
- SPEC coverage currently has no `implemented-untested` or `blocked-external` rows; `FULL_SPEC_REMAINING.md` lines 19-25 list none.

## What is unproven

- R-063 and R-069 remain partial in `SPEC_COVERAGE.md` lines 70 and 76: full `./install.sh --non-interactive` twice on Ubuntu is still unrun because it has package/service side effects in this environment.
- R-075 remains partial in `SPEC_COVERAGE.md` line 82: deterministic fake workers cover orchestration paths, but full live multi-agent swarm workload-control behavior is not proven.
- `scripts/smoke_integration.sh` has syntax coverage only; the newly added script has not been run end-to-end in this session because it requires a live provider, running server, and Pi install.

## What is broken or risky

- No newly identified concrete broken behavior remains from this pass. The remaining risks require side-effecting install or live multi-agent workload evidence.

## Recommended next action

Run the final full verification matrix, then commit and push the production-hardening pass. If more evidence is needed later, prioritize side-effecting full install idempotency and a live multi-agent workload run in an isolated environment.

## Effort estimate

| item | estimated hours | risk (low/med/high) |
|---|---:|---|
| Full noninteractive install twice in an isolated Ubuntu environment | 2 | med |
| Live multi-agent workload-control proof run | 3 | med |
