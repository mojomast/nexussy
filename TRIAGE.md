## What is solid

- Resolved: smoke SSE parsing now reads the next non-empty `data:` line after `event: done`, and `scripts/test_smoke_parser.sh` proves core-style multiline frames locally.
- Resolved: the smoke script now uses the verified `ChangedFilesManifest.files` field instead of `changed_files`.
- Resolved: `NEXUSSY_PI_COMMAND` handling now preserves executable paths with spaces, supports command strings with args, and posts `pi_command` plus `pi_args` separately.
- Resolved: the engine compatibility wrapper no longer mutates `develop.spawn_pi_worker` globally; tests pass `spawn_fn` explicitly.
- Resolved: secret set/delete routes invalidate the provider env cache, and core tests prove subsequent provider calls see updated and removed keys.
- Resolved: R-040 plan task validation repairs missing owner, acceptance criteria, and tests while preserving provider plan content.
- Resolved: R-058/R-067 now define OpenTUI as the default TUI renderer with `NEXUSSY_TUI_RENDERER=pi-tui` as the Pi TUI opt-in path.
- Resolved: R-063/R-069 full Ubuntu 22.04 noninteractive install idempotency is proven by `scripts/evidence/install_idempotency_run1.txt` and `scripts/evidence/install_idempotency_run2.txt`.
- Resolved: R-075 live multi-agent swarm workload control is proven by `scripts/evidence/swarm_proof_run.json` with backend/frontend workers, pause/resume, final passed status, and develop/merge/changed-files artifacts.
- Resolved: `FULL_SPEC_REMAINING.md` stale local/team hardening “in progress” text is cleared.
- Resolved: develop stage now slices the devplan artifact into atomic task specs (`_slice_devplan_tasks`) and dispatches one JSON-encoded spec per worker via the Pi RPC `request` payload.
- Resolved: orchestrator and worker steering is wired through the `nexussy_steer` MCP tool and the `steer_events` SQLite table; orchestrator-target messages drain into `engine.steer_context[run_id]` at each stage boundary; worker-target messages flow through the existing inject path.
- Resolved: interview stage auto-skips human gating when `metadata.skip_interview == "true"`, synthesizing all answers via the configured provider and marking each `InterviewQuestionAnswer.source = "auto"`.
- Resolved: develop merge conflicts are now recovered automatically — `merge_single_worker` saves a `conflict_report` artifact, runs `git checkout --ours` + `git add` for each conflicting path, attempts `git commit --no-edit`, and only raises if the second commit also fails.
- Core regression suite is green: `python3 -m pytest -q core/tests` passed with 97 tests and 3 existing warnings.
- TUI regression suite is green: `bun test && bun run typecheck` passed with 67 tests.
- Web regression suite is green: `python3 -m pytest -q web/tests` passed with 52 tests.
- Root operations checks are green: shell syntax, `./ops_tests.sh`, and `./install.sh --non-interactive --dry-run` pass.
- `scripts/smoke_integration.sh` syntax and parser harness pass: `bash -n scripts/smoke_integration.sh`; `bash scripts/test_smoke_parser.sh`.
- CI has the expected four verification jobs plus Docker gating: `.github/workflows/ci.yml` defines `core`, `tui`, `web`, `ops`, and `docker-build`, with `docker-build.needs: [core, tui, web, ops]`.
- CI uses `python3` for Python install, Ruff, core tests, web deps, and web tests in `.github/workflows/ci.yml` lines 21-28 and 63-67.
- The stage split is present: `core/nexussy/pipeline/stages/` contains `interview.py`, `design.py`, `validate.py`, `plan.py`, `review.py`, and `develop.py`.
- `core/nexussy/pipeline/engine.py` is under the target at 299 lines and still imports `nexussy.pipeline.engine` as the public orchestrator module.
- The web dashboard multi-answer flow is present: `web/nexussy_web/static/app.js` lines 160-188 renders all candidate questions into `#interview-fields`, and lines 280-293 builds and posts a full `answers` map.
- SPEC coverage currently has no partial, `implemented-untested`, or `blocked-external` rows; `FULL_SPEC_REMAINING.md` lists no remaining work.

## What is unproven

- None. All SPEC rows are covered by deterministic tests, live evidence, or operational evidence files.

## What is broken or risky

- No newly identified concrete broken behavior remains from this pass.

## Recommended next action

No remaining SPEC coverage action is required. Keep rerunning the standard verification matrix before future releases.

## Effort estimate

No remaining items.
