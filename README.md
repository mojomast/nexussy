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

Start the terminal UI after core is healthy:

```bash
./nexussy.sh start-tui
```

The TUI consumes only the core HTTP/SSE API and writes its launcher log to `/tmp/nexussy-tui.log`.

## Web dashboard

The web dashboard starts with `./nexussy.sh start` and listens on `http://127.0.0.1:7772`. It proxies `/api/*` calls and SSE streams to core.

## Mock mode and production gates

nexussy can be exercised in explicit mock mode with request metadata such as `{"metadata":{"mock_provider":true}}`; this is suitable for local UI and pipeline smoke checks without provider secrets. Deterministic production-path provider testing can use `NEXUSSY_PROVIDER_MODE=fake`. Production provider execution uses LiteLLM and requires at least one configured provider key in `~/.nexussy/.env` or the OS keyring. Production swarm development uses the Pi RPC subprocess adapter and requires the `pi` command (or `NEXUSSY_PI_COMMAND`) to be installed for live Pi workers. `./nexussy.sh doctor` reports provider-key and Pi readiness without crashing.

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

Set `NEXUSSY_API_KEY` when API auth is enabled. Set provider keys in the OS keyring through nexussy secrets flows when available, or fill placeholders in `~/.nexussy/.env`:

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `XAI_API_KEY`, `GLM_API_KEY`, `ZAI_API_KEY`, `REQUESTY_API_KEY`, `AETHER_API_KEY`, and `OLLAMA_BASE_URL`.

## Update

```bash
./nexussy.sh update
```

This runs `git pull`, reinstalls core and web editable packages, and runs `bun install` for the TUI.
