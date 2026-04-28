# nexussy

nexussy is the fifth-generation Ussyverse coding harness lineage: `devussy -> swarmussy -> ralphussy -> geoffrussy -> nexussy`.
It runs an interview-to-design-to-plan-to-review-to-develop pipeline with a live role-based swarm, anchored handoffs, git worktree isolation, checkpoint resumption, and local control surfaces.

## Install

Prerequisites: Python 3.11+ (the scripts try `python3.13`, `python3.12`, `python3.11`, `python3`, then `python`), Bun 1.x+, git, and curl. On PEP 668 distributions such as Ubuntu 24.04, the installer creates `~/.nexussy/venv` and installs editable core/web packages inside that venv.

```bash
./install.sh --non-interactive
```

Preview dependency checks and intended actions without creating config, env, venv, PID, package, or service files:

```bash
./install.sh --non-interactive --dry-run
```

Interactive installs may offer keyring guidance. Noninteractive mode never prompts. Optional systemd user units are generated only when requested:

```bash
./install.sh --systemd-user
```

The installer creates `~/.nexussy/`, `~/.nexussy/run/`, `~/.nexussy/logs/`, `~/.nexussy/nexussy.yaml`, and `~/.nexussy/.env` only when absent, then installs core, TUI, and web packages. Reruns preserve existing config and env files unchanged.

## Start and stop

```bash
./nexussy.sh start      # starts core on 127.0.0.1:7771 and web on 127.0.0.1:7772
./nexussy.sh status     # prints health, ports, PID files, and config path
./nexussy.sh stop       # stops TUI, web, and core from PID files
./nexussy.sh doctor     # checks dependencies, config, ports, Pi, and provider keys
```

To start core/web, verify health, and print the TUI launch instructions in one step:

```bash
./launch_verify.sh
```

Logs:

```bash
./nexussy.sh logs core
./nexussy.sh logs web
./nexussy.sh logs tui
# Non-following form, useful for smoke tests and CI:
./nexussy.sh logs --no-follow core
```

## Operational smoke tests

Root-only user-space checks cover duplicate start prevention, stale PID cleanup, dry-run no writes, idempotent config/env generation, the logs command, and doctor diagnostics:

```bash
bash -n install.sh nexussy.sh ops_tests.sh
./ops_tests.sh
```

## Spec coverage

The authoritative contract is `SPEC.md`. Current traceability evidence is tracked in `SPEC_COVERAGE.md`; deterministic implementation paths are tested locally, while only live external checks that require unavailable credentials/tools are marked blocked-external.

Required local verification:

```bash
python3 -m pytest -q core/tests
cd tui && bun install && bun test && bun run typecheck
cd ..
python3 -m pytest -q web/tests
bash -n install.sh nexussy.sh ops_tests.sh
./install.sh --non-interactive --dry-run
./ops_tests.sh
```

## TUI

Start the interactive terminal UI after core is healthy:

```bash
./nexussy.sh start-tui
```

The TUI consumes only the core HTTP/SSE API and stays attached to the current terminal. Type `/quit` to exit.

Provider/model setup is available as a single-terminal wizard. If core is not already running, the TUI starts a local core process for setup and stops the process when setup finishes:

```bash
cd tui
bun run start -- --setup
```

The wizard currently supports OpenRouter, OpenAI, and Anthropic provider choices. For OpenRouter, it prompts for `OPENROUTER_API_KEY` and lets you choose a model for all pipeline stages. To go directly to OpenRouter setup:

```bash
cd tui
bun run start -- --setup-openrouter
```

Direct hidden-input key setup is also available:

```bash
cd tui
bun run start -- --set-key OPENAI_API_KEY
```

The prompt does not echo secret values. Core stores keys in the OS keyring when available and falls back to the configured env file. If the local keyring backend hangs or is unavailable, core falls back to the env file after a short timeout. Model choices are persisted to the configured YAML file. Inside the TUI, use `/secrets` to refresh provider key status and `/delete-key NAME` to remove a configured key; the UI displays only `configured`/`missing` summaries and never renders secret values.

## Web dashboard

The web dashboard starts with `./nexussy.sh start` and listens on `http://127.0.0.1:7772`. It proxies `/api/*` calls and SSE streams to core.

## Interview API

The pipeline starts with an interview stage that generates 4-8 plain-language questions and stores the answered `InterviewArtifact` for downstream design and devplan prompts.

For automated runs and CI, set `auto_approve_interview` to `true`; core generates questions, synthesizes answers from `description`, and continues without user input:

```bash
curl -s http://127.0.0.1:7771/pipeline/start \
  -H 'Content-Type: application/json' \
  -d '{"project_name":"HabitTrack","description":"A Python REST API for tracking habits","auto_approve_interview":true}'
```

For interactive runs, omit `auto_approve_interview` or set it to `false`. The run pauses after writing `.nexussy/artifacts/interview.json` with pending questions. Read the artifact through `GET /pipeline/artifacts/interview?session_id=<session_id>`, then submit answers:

```bash
curl -s http://127.0.0.1:7771/pipeline/<session_id>/interview/answer \
  -H 'Content-Type: application/json' \
  -d '{"answers":{"q_name":"HabitTrack","q_lang":"Python","q_desc":"A REST API for tracking habits","q_type":"API"}}'
```

After every question has a non-empty answer, the pipeline resumes into design with the interview summary injected into downstream prompts.

## Validation, review, and resume

The validate and review stages use the configured provider instead of fixed stubs. Validate checks the design draft for completeness, consistency, dependencies, risks, and test strategy, then writes `validated_design` and `validation_report`. Review checks `devplan` and `handoff` for gaps, ambiguous assignments, and development risks, then writes `review_report`. Failed validate/review reports retry through the existing design/plan correction loops until the configured iteration limit is reached.

The plan stage writes the provider-generated `devplan` body when it includes the required anchors. If the provider omits `NEXT_TASK_GROUP` anchors, core repairs the first checklist it can find or falls back to a safe anchored template and emits a warning event.

Core persists stage checkpoints and supports resume requests with `resume_run_id`. When a later checkpoint exists, the resumed run starts after the latest checkpointed stage instead of replaying completed stages.

## MCP tools

Core exposes a minimal MCP tool surface for external agents:

- `GET /mcp/tools` lists registered tools and their `inputSchema` values.
- `POST /mcp/call` invokes a tool by name with `arguments`.
- Built-in tools include `nexussy_start_pipeline` and `nexussy_get_status`.

## Mock mode and production gates

nexussy can be exercised in explicit mock mode with request metadata such as `{"metadata":{"mock_provider":true}}`; this is suitable for local UI and pipeline smoke checks without provider secrets. Deterministic production-path provider testing can use `NEXUSSY_PROVIDER_MODE=fake`. Production provider execution uses LiteLLM and requires at least one configured provider key in `~/.nexussy/.env` or the OS keyring. Rate-limited provider starts return `429` with `Retry-After` when a reset time is known. Production swarm development uses the Pi RPC subprocess adapter and requires the `pi` command (or `NEXUSSY_PI_COMMAND`) to be installed for live Pi workers. `./nexussy.sh doctor` reports provider-key and Pi readiness without crashing.

Missing provider credentials must fail explicitly with the spec-defined provider/model error and must not silently run mock mode.

## Configuration

Default config lives at `~/.nexussy/nexussy.yaml`; local environment placeholders live at `~/.nexussy/.env`. Override paths with `NEXUSSY_HOME`, `NEXUSSY_CONFIG`, and `NEXUSSY_ENV_FILE`.

Important defaults:

- Core: `127.0.0.1:7771`
- Web: `127.0.0.1:7772`
- Core CORS: `http://127.0.0.1:7772`
- Web core base URL: `http://127.0.0.1:7771`
- Auth header: `X-API-Key` when auth is enabled
- Projects: `~/nexussy-projects/`
- Global DB: `~/.nexussy/state.db`

## Provider keys

Set `NEXUSSY_API_KEY` when API auth is enabled. This is separate from provider keys. Set provider keys through guided TUI setup when possible, or fill placeholders in `~/.nexussy/.env`:

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `XAI_API_KEY`, `GLM_API_KEY`, `ZAI_API_KEY`, `REQUESTY_API_KEY`, `AETHER_API_KEY`, and `OLLAMA_BASE_URL`.

## Update

```bash
./nexussy.sh update
```

This runs `git pull`, reinstalls core and web editable packages, and runs `bun install` for the TUI.
