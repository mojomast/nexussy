# nexussy

nexussy is a local software-delivery harness for running a complete AI-assisted development pipeline from one project request. It turns a project description into interview answers, design artifacts, a dev plan, review feedback, worker execution, merge reports, changed-file manifests, and handoff documents that another agent or human can continue from without needing the original chat history.

It is the fifth-generation Ussyverse coding harness lineage:

`devussy -> swarmussy -> ralphussy -> geoffrussy -> nexussy`

## What It Does

nexussy is not a chat app. It is a local control plane for staged software delivery.

The core workflow is:

1. Interview the project owner when requirements are incomplete.
2. Generate design and complexity artifacts.
3. Validate the design and retry corrections when needed.
4. Generate an anchored `devplan.md`, phase files, and `handoff.md`.
5. Review the plan and route feedback back to planning when needed.
6. Run role-based development workers in isolated git worktrees.
7. Merge worker output serially, extract changed files, and write reports.
8. Stream every important state transition over SSE to local UIs.

The result is a traceable run with durable artifacts, resumable checkpoints, and enough anchored context to safely continue later.

## Main Capabilities

- Six-stage pipeline: `interview -> design -> validate -> plan -> review -> develop`.
- Provider-backed stages through LiteLLM-compatible models.
- Explicit mock/fake provider modes for deterministic local testing.
- Manual or auto-approved interview flow.
- Anchored `devplan.md`, `phaseNNN.md`, and `handoff.md` generation.
- Stage retry loops for validation and review feedback.
- SQLite WAL-backed run, event, artifact, worker, blocker, and memory state.
- SSE event stream with replay, heartbeat, slow-client handling, and typed payloads.
- Git worktree isolation for worker execution.
- Pi RPC subprocess adapter for live worker execution, with a bundled deterministic fallback for local tests.
- Pause, resume, skip, cancel, inject, blocker, and worker controls.
- Terminal UI for setup and day-to-day control.
- Web dashboard for observing health, runs, artifacts, workers, config, secrets, and SSE activity.
- MCP-compatible tool surface for external agents.
- Root installer and launcher scripts with dry-run, doctor, logs, status, update, and optional systemd-user support.

## Architecture

```text
tui/ nexussy-tui
  TypeScript + Bun + OpenTUI/Pi-compatible control surface
  Uses only core HTTP and SSE APIs

core/ nexussy-core
  Python + Starlette + SQLite + LiteLLM + Pi subprocess adapter
  Owns pipeline state, artifacts, providers, workers, checkpoints, and SSE

web/ nexussy-web
  Python + Starlette single-page dashboard
  Proxies /api/* and SSE to core
```

Default local ports:

- Core: `http://127.0.0.1:7771`
- Web dashboard: `http://127.0.0.1:7772`
- TUI: terminal process only, no port

## Repository Layout

```text
core/      Python core API, pipeline, providers, artifacts, SQLite, swarm, MCP
tui/       TypeScript/Bun terminal UI and tests
web/       Starlette dashboard and proxy
install.sh User-space installer
nexussy.sh Runtime launcher and diagnostics
SPEC.md    Authoritative implementation contract
```

`SPEC.md` is the source of truth for contracts. `SPEC_COVERAGE.md` tracks implementation evidence and remaining gaps.

## Install

Prerequisites:

- Python 3.11+
- Bun 1.x+
- git
- curl

Install in user space:

```bash
./install.sh --non-interactive
```

Preview dependency checks and intended actions without creating config, env, venv, PID, package, or service files:

```bash
./install.sh --non-interactive --dry-run
```

Generate optional systemd user units:

```bash
./install.sh --systemd-user
```

The installer creates these only when absent:

- `~/.nexussy/`
- `~/.nexussy/run/`
- `~/.nexussy/logs/`
- `~/.nexussy/nexussy.yaml`
- `~/.nexussy/.env`
- `~/.nexussy/venv` on PEP 668 distributions

Reruns preserve existing config, env, and generated systemd user unit files.

## Start, Stop, And Diagnose

```bash
./nexussy.sh start      # start core and web
./nexussy.sh status     # show config path, ports, PID files, and health
./nexussy.sh stop       # stop TUI, web, and core from PID files
./nexussy.sh doctor     # check dependencies, config, ports, Pi, and provider keys
./nexussy.sh update     # git pull, reinstall core/web, run bun install for TUI
```

Start core/web, verify health, and print TUI instructions:

```bash
./launch_verify.sh
```

Logs:

```bash
./nexussy.sh logs core
./nexussy.sh logs web
./nexussy.sh logs tui
./nexussy.sh logs --no-follow core
```

## TUI

Start the interactive terminal UI after core is healthy:

```bash
./nexussy.sh start-tui
```

The TUI is a control surface over the core API. It does not own provider secrets or pipeline state.

Useful TUI setup commands:

```bash
cd tui
bun run start -- --setup
bun run start -- --setup-openrouter
bun run start -- --set-key OPENAI_API_KEY
```

Inside the TUI:

- `/secrets` refreshes provider-key status.
- `/delete-key NAME` deletes a configured provider key.
- `/new DESCRIPTION` starts an explicit pipeline run.
- `/pause`, `/resume`, `/skip`, `/stage`, `/spawn`, `/inject`, and `/export` control active runs.

Ordinary chat-like text stays in local Ask mode unless an explicit action command is used.

## Web Dashboard

The web dashboard is available after `./nexussy.sh start`:

```text
http://127.0.0.1:7772
```

It provides browser-visible panels for:

- Core health
- Run streams and SSE errors
- Stage state and transitions
- Worker state
- File locks and git events
- Artifacts and DevPlan anchors
- Config editing
- Secret controls
- Memory and graph routes

The dashboard proxies `/api/*` to core and does not implement pipeline business logic itself.

## Starting A Pipeline Run

Automated run with interview auto-approval:

```bash
curl -s http://127.0.0.1:7771/pipeline/start \
  -H 'Content-Type: application/json' \
  -d '{
    "project_name":"HabitTrack",
    "description":"A Python REST API for tracking habits",
    "auto_approve_interview":true
  }'
```

Manual interview flow:

1. Start a run with `auto_approve_interview` omitted or `false`.
2. Read the interview artifact from `GET /pipeline/artifacts/interview?session_id=<session_id>`.
3. Submit answers to `POST /pipeline/<session_id>/interview/answer`.

Example answer request:

```bash
curl -s http://127.0.0.1:7771/pipeline/<session_id>/interview/answer \
  -H 'Content-Type: application/json' \
  -d '{
    "answers": {
      "q_name":"HabitTrack",
      "q_lang":"Python",
      "q_desc":"A REST API for tracking habits",
      "q_type":"API"
    }
  }'
```

Manual interview waits time out according to `stages.interview.answer_timeout_s`; timeout cleanup clears paused state before the run is marked failed.

## Provider Modes

Production provider execution uses LiteLLM and a configured provider key.

Supported key names include:

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `XAI_API_KEY`, `GLM_API_KEY`, `ZAI_API_KEY`, `REQUESTY_API_KEY`, `AETHER_API_KEY`, and `OLLAMA_BASE_URL`.

Local development modes:

- Request metadata `{"mock_provider": true}` enables explicit mock output for a run.
- `NEXUSSY_PROVIDER_MODE=fake` exercises the production path with deterministic fake provider output.
- Missing provider credentials fail explicitly with provider/model errors; core does not silently fall back to mock mode.

`NEXUSSY_MOCK_PROVIDER=1` is for local development only. Do not use it in production.

## Pi Worker Execution

The develop stage uses the Pi RPC subprocess adapter for live workers. If an external `pi` command is unavailable, deterministic local runs can use nexussy's bundled Pi-compatible fallback.

Worker behavior:

- Workers spawn and run in parallel.
- Git merges happen serially to keep conflict handling deterministic.
- Worker RPC resume is guarded at max depth 3.
- Worker output is streamed into SSE events.
- Changed files are extracted into artifacts after merge.

Live Pi execution requires the `pi` command or `NEXUSSY_PI_COMMAND` to point at a compatible executable.

## Artifacts

Pipeline artifacts are written under the project main worktree, typically:

```text
~/nexussy-projects/<project_slug>/main/.nexussy/artifacts/
```

Important artifacts include:

- `interview.json`
- `complexity_profile.json`
- `design_draft.md`
- `validated_design.md`
- `validation_report.json`
- `devplan.md`
- `handoff.md`
- `phaseNNN.md`
- `review_report.json`
- `develop_report.json`
- `merge_report.json`
- `changed_files.json`

Anchored `devplan.md`, `phaseNNN.md`, and `handoff.md` files are designed for safe continuation by another agent.

## MCP Tools

Core exposes a small MCP-compatible tool surface:

- `GET /mcp/tools` lists registered tools and their `inputSchema` values.
- `POST /mcp/call` invokes a tool by name with `arguments`.
- `nexussy_start_pipeline` starts a pipeline run.
- `nexussy_get_status` returns pipeline status.

The stdio JSON-RPC MCP path supports initialization, tool listing, and tool calls.

## Security

Secrets:

- Core resolves provider secrets from OS keyring first, process/environment variables second, and the configured env file last.
- Guided setup stores keys in the OS keyring when available.
- If keyring is unavailable or times out, core falls back to the env file and logs a plaintext-storage warning.
- UI/API summaries report configured/missing status and never return secret values.

CORS:

```yaml
security:
  cors_origins:
    - "https://your-dashboard.example"
```

- Default `cors_origins: ["*"]` preserves local compatibility.
- Set `NEXUSSY_ENV=production` for production mode.
- In production, wildcard CORS is rejected unless `NEXUSSY_ALLOW_WILDCARD_CORS=1` is explicitly set.
- Deployment automation may use `NEXUSSY_CORS_ORIGINS` and map it into `nexussy.yaml` before startup.

Other safeguards:

- Paths are resolved through sanitizer helpers.
- Symlink escapes are rejected when enabled.
- Logs scrub common API key, bearer token, password, private key, and context-guarded secret hash forms.
- Worker writes require file locks.
- SQLite writes are serialized with WAL, busy timeout, retries, and indexed run lookups.

## Configuration

Default config lives at:

```text
~/.nexussy/nexussy.yaml
```

Local environment placeholders live at:

```text
~/.nexussy/.env
```

Common environment overrides:

- `NEXUSSY_HOME`
- `NEXUSSY_CONFIG`
- `NEXUSSY_ENV_FILE`
- `NEXUSSY_PROJECTS_DIR`
- `NEXUSSY_CORE_HOST`
- `NEXUSSY_CORE_PORT`
- `NEXUSSY_WEB_HOST`
- `NEXUSSY_WEB_PORT`
- `NEXUSSY_API_KEY`
- `NEXUSSY_AUTH_ENABLED`
- `NEXUSSY_DEFAULT_MODEL`
- `NEXUSSY_PI_COMMAND`
- `NEXUSSY_ENV`
- `NEXUSSY_ALLOW_WILDCARD_CORS`

## Verification

Full local verification:

```bash
python3 -m pytest -q core/tests
cd tui && bun install && bun test && bun run typecheck
cd ..
python3 -m pytest -q web/tests
bash -n install.sh nexussy.sh ops_tests.sh launch_verify.sh
./install.sh --non-interactive --dry-run
./ops_tests.sh
```

Current traceability status is tracked in `SPEC_COVERAGE.md` and `FULL_SPEC_REMAINING.md`. At the time of this README update, no rows are blocked on missing external tooling. The main remaining partial evidence item is a single full production-provider plus live-Pi develop run because that can spend provider tokens and modify a throwaway worktree.

## Development Notes

- Follow `SPEC.md` for contracts.
- Follow `AGENTS.md` for ownership boundaries and handoff protocol.
- Use `CIRCULAR_DEVELOPMENT.md` when closing coverage gaps sequentially.
- Do not depend on `ussycode`.
- Do not log secrets.
- Recent fixes include keyring fallback warning behavior, automatic 429 rate-limit persistence from provider completions, narrowed file-lock DB exception handling, rename-diff parsing, unique mock develop worker IDs, event-based Pi RPC response waiting, numeric config coercion, and expanded security tests.

## Update

```bash
./nexussy.sh update
```

This runs `git pull`, reinstalls core and web editable packages, and runs `bun install` for the TUI.
