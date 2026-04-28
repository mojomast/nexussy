#!/usr/bin/env bash
set -u

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
NEXUSSY_HOME=${NEXUSSY_HOME:-"$HOME/.nexussy"}
NEXUSSY_CONFIG=${NEXUSSY_CONFIG:-"$NEXUSSY_HOME/nexussy.yaml"}
NEXUSSY_ENV_FILE=${NEXUSSY_ENV_FILE:-"$NEXUSSY_HOME/.env"}
RUN_DIR="$NEXUSSY_HOME/run"
LOG_DIR="$NEXUSSY_HOME/logs"
VENV_DIR=${NEXUSSY_VENV:-"$NEXUSSY_HOME/venv"}
NON_INTERACTIVE=0
SYSTEMD_USER=0
DRY_RUN=0

usage() {
  printf '%s\n' "Usage: ./install.sh [--non-interactive] [--dry-run] [--systemd-user]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --systemd-user) SYSTEMD_USER=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf '%s\n' "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

info() { printf '%s\n' "[nexussy] $*"; }
warn() { printf '%s\n' "[nexussy] WARN: $*" >&2; }
fail() { printf '%s\n' "[nexussy] ERROR: $*" >&2; exit 1; }
dry() { if [ "$DRY_RUN" -eq 1 ]; then info "DRY-RUN: $*"; fi; }

have() { command -v "$1" >/dev/null 2>&1; }

python_cmd() {
  for c in python3.13 python3.12 python3.11 python3 python; do
    if have "$c" && "$c" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

check_deps() {
  PYTHON=$(python_cmd) || fail "Python 3.11+ is required. Remediation: install Python 3.11+ (Ubuntu: sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3-pip)."
  export PYTHON
  BUN_VERSION=$(bun --version 2>/dev/null || true)
  if [ -z "$BUN_VERSION" ]; then
    fail "Bun 1.x+ is required. Remediation: install Bun with: curl -fsSL https://bun.sh/install | bash"
  fi
  case "$BUN_VERSION" in
    1.*) : ;;
    *) fail "Bun 1.x+ is required, found '$BUN_VERSION'. Remediation: install Bun 1.x from https://bun.sh." ;;
  esac
  have git || fail "git is required. Remediation: sudo apt-get update && sudo apt-get install -y git"
  have curl || fail "curl is required. Remediation: sudo apt-get update && sudo apt-get install -y curl"
  info "Using Python: $PYTHON"
  info "Using Bun: $BUN_VERSION"
  if have shellcheck; then info "Optional shellcheck: $(shellcheck --version 2>/dev/null | awk 'NR==2 {print $2; exit}' 2>/dev/null || printf 'available')"; else warn "Optional shellcheck not found; install shellcheck for script linting."; fi
}

ensure_venv() {
  if [ "$DRY_RUN" -eq 1 ]; then
    dry "would create/reuse virtual environment at $VENV_DIR using $PYTHON, then run $VENV_DIR/bin/python -m pip install ..."
    return 0
  fi
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    info "Creating Python virtual environment: $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR" || fail "Virtual environment creation failed. Remediation: install venv support (Ubuntu: sudo apt-get install -y python3-venv python3-full), then rerun ./install.sh --non-interactive"
  fi
  PYTHON="$VENV_DIR/bin/python"
  export PYTHON
  "$PYTHON" -m pip install --upgrade pip >/dev/null || fail "pip upgrade failed inside $VENV_DIR. Remediation: remove $VENV_DIR and rerun ./install.sh --non-interactive"
  info "Using install Python: $PYTHON"
}

write_config_if_absent() {
  if [ -e "$NEXUSSY_CONFIG" ]; then
    info "Keeping existing config: $NEXUSSY_CONFIG"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then dry "would create config: $NEXUSSY_CONFIG"; return 0; fi
  tmp="$NEXUSSY_CONFIG.tmp.$$"
  cat > "$tmp" <<'YAML'
version: "1.0"
home_dir: "~/.nexussy"
projects_dir: "~/nexussy-projects"
core:
  host: "127.0.0.1"
  port: 7771
  cors_allow_origins: ["http://127.0.0.1:7772"]
web:
  host: "127.0.0.1"
  port: 7772
  core_base_url: "http://127.0.0.1:7771"
auth:
  enabled: false
  api_key_env: "NEXUSSY_API_KEY"
  header_name: "X-API-Key"
database:
  global_path: "~/.nexussy/state.db"
  project_relative_path: ".nexussy/state.db"
  wal_enabled: true
  busy_timeout_ms: 5000
  write_retry_count: 5
  write_retry_base_ms: 100
providers:
  default_model: "openai/gpt-5.5-fast"
  allow_fallback: false
  request_timeout_s: 120
  max_retries: 3
  retry_base_ms: 500
stages:
  interview:
    model: "openai/gpt-5.5-fast"
    max_retries: 3
  design:
    model: "openai/gpt-5.5-fast"
    max_retries: 3
  validate:
    model: "openai/gpt-5.5-fast"
    max_iterations: 3
    max_retries: 2
  plan:
    model: "openai/gpt-5.5-fast"
    max_retries: 3
  review:
    model: "openai/gpt-5.5-fast"
    max_iterations: 2
    max_retries: 2
  develop:
    model: "openai/gpt-5.5-fast"
    orchestrator_model: "openai/gpt-5.5-fast"
    max_retries: 2
swarm:
  max_workers: 8
  default_worker_count: 2
  worker_task_timeout_s: 900
  worker_start_timeout_s: 30
  file_lock_timeout_s: 120
  file_lock_retry_ms: 250
  merge_strategy: "no_ff"
pi:
  command: "pi"
  args: ["--rpc"]
  startup_timeout_s: 30
  shutdown_timeout_s: 10
  max_stdout_line_bytes: 1048576
sse:
  heartbeat_interval_s: 15
  client_queue_max_events: 1000
  replay_max_events: 10000
  retry_ms: 3000
security:
  scrub_logs: true
  reject_symlink_escape: true
  keyring_service: "nexussy"
logging:
  level: "INFO"
  core_log_file: "/tmp/nexussy-core.log"
  web_log_file: "/tmp/nexussy-web.log"
  tui_log_file: "/tmp/nexussy-tui.log"
YAML
  mv "$tmp" "$NEXUSSY_CONFIG"
  info "Created config: $NEXUSSY_CONFIG"
}

write_env_if_absent() {
  if [ -e "$NEXUSSY_ENV_FILE" ]; then
    info "Keeping existing env file: $NEXUSSY_ENV_FILE"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then dry "would create env file: $NEXUSSY_ENV_FILE with NEXUSSY_API_KEY and provider placeholders"; return 0; fi
  tmp="$NEXUSSY_ENV_FILE.tmp.$$"
  cat > "$tmp" <<'ENV'
# nexussy local environment. Leave placeholders empty until configured.
NEXUSSY_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
MISTRAL_API_KEY=
TOGETHER_API_KEY=
FIREWORKS_API_KEY=
XAI_API_KEY=
GLM_API_KEY=
ZAI_API_KEY=
REQUESTY_API_KEY=
AETHER_API_KEY=
OLLAMA_BASE_URL=
ENV
  chmod 600 "$tmp"
  mv "$tmp" "$NEXUSSY_ENV_FILE"
  info "Created env file: $NEXUSSY_ENV_FILE"
}

prompt_keyring() {
  if [ "$NON_INTERACTIVE" -eq 1 ] || [ ! -t 0 ]; then
    return 0
  fi
  printf '%s' "Set up provider keys in OS keyring now? [y/N] "
  read -r answer || answer=
  case "$answer" in
    y|Y|yes|YES) info "Keyring setup is handled by the nexussy UI/API secrets routes; keep .env placeholders empty for keyring-backed secrets." ;;
    *) info "Skipping keyring setup." ;;
  esac
}

install_packages() {
  if [ "$DRY_RUN" -eq 1 ]; then
    dry "would run: $PYTHON -m pip install -e core/"
    dry "would run: cd tui && bun install"
    dry "would run: $PYTHON -m pip install -e web/"
    return 0
  fi
  info "Installing core package"
  (cd "$ROOT_DIR" && "$PYTHON" -m pip install -e core/) || fail "Core install failed. Remediation: $PYTHON -m pip install -e core/"
  info "Installing TUI dependencies"
  (cd "$ROOT_DIR/tui" && bun install) || fail "TUI install failed. Remediation: cd tui && bun install"
  info "Installing web package"
  (cd "$ROOT_DIR" && "$PYTHON" -m pip install -e web/) || fail "Web install failed. Remediation: $PYTHON -m pip install -e web/"
}

write_systemd_user() {
  [ "$SYSTEMD_USER" -eq 1 ] || return 0
  if [ "$DRY_RUN" -eq 1 ]; then dry "would write systemd user units under $HOME/.config/systemd/user"; return 0; fi
  unit_dir="$HOME/.config/systemd/user"
  python_path=$(command -v "$PYTHON")
  mkdir -p "$unit_dir"
  # Idempotency contract: generated user units are created only when absent so
  # rerunning install does not overwrite local systemd customizations.
  if [ -e "$unit_dir/nexussy-core.service" ]; then
    info "Keeping existing systemd user unit: $unit_dir/nexussy-core.service"
  else
    tmp="$unit_dir/nexussy-core.service.tmp.$$"
    cat > "$tmp" <<EOF
[Unit]
Description=nexussy core

[Service]
WorkingDirectory=$ROOT_DIR
Environment=NEXUSSY_CONFIG=$NEXUSSY_CONFIG
Environment=NEXUSSY_ENV_FILE=$NEXUSSY_ENV_FILE
ExecStart=$python_path -m nexussy.api.server
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    mv "$tmp" "$unit_dir/nexussy-core.service"
    info "Created systemd user unit: $unit_dir/nexussy-core.service"
  fi
  if [ -e "$unit_dir/nexussy-web.service" ]; then
    info "Keeping existing systemd user unit: $unit_dir/nexussy-web.service"
  else
    tmp="$unit_dir/nexussy-web.service.tmp.$$"
    cat > "$tmp" <<EOF
[Unit]
Description=nexussy web
After=nexussy-core.service

[Service]
WorkingDirectory=$ROOT_DIR
Environment=NEXUSSY_CONFIG=$NEXUSSY_CONFIG
Environment=NEXUSSY_ENV_FILE=$NEXUSSY_ENV_FILE
ExecStart=$python_path -m nexussy_web.app
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    mv "$tmp" "$unit_dir/nexussy-web.service"
    info "Created systemd user unit: $unit_dir/nexussy-web.service"
  fi
  info "Enable with: systemctl --user daemon-reload && systemctl --user enable --now nexussy-core.service nexussy-web.service"
}

health_check() {
  if [ "$DRY_RUN" -eq 1 ]; then dry "would start temporary core and call http://127.0.0.1:7771/health"; return 0; fi
  info "Running temporary core health check"
  if curl -fsS "http://127.0.0.1:7771/health" >/dev/null 2>&1; then
    info "Core health check passed on existing service"
    return 0
  fi
  rm -f "$RUN_DIR/install-core.pid"
  old_pwd=$(pwd)
  cd "$ROOT_DIR" || fail "Cannot enter repository root: $ROOT_DIR"
  NEXUSSY_CONFIG="$NEXUSSY_CONFIG" NEXUSSY_ENV_FILE="$NEXUSSY_ENV_FILE" nohup "$PYTHON" -m nexussy.api.server >> /tmp/nexussy-core.log 2>&1 &
  printf '%s\n' "$!" > "$RUN_DIR/install-core.pid"
  cd "$old_pwd" || fail "Cannot return to previous directory: $old_pwd"
  pid=$(cat "$RUN_DIR/install-core.pid" 2>/dev/null || true)
  i=0
  while [ "$i" -lt 30 ]; do
    if curl -fsS "http://127.0.0.1:7771/health" >/dev/null 2>&1; then
      if [ -n "$pid" ]; then
        kill "$pid" >/dev/null 2>&1 || true
        sleep 1
        kill -0 "$pid" >/dev/null 2>&1 && kill -9 "$pid" >/dev/null 2>&1 || true
      fi
      rm -f "$RUN_DIR/install-core.pid"
      info "Temporary core health check passed"
      return 0
    fi
    if [ -n "$pid" ] && ! kill -0 "$pid" >/dev/null 2>&1; then
      break
    fi
    i=$((i + 1))
    sleep 1
  done
  if [ -n "$pid" ]; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    kill -0 "$pid" >/dev/null 2>&1 && kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$RUN_DIR/install-core.pid"
  fail "Core health check failed. Remediation: inspect /tmp/nexussy-core.log, then run: $PYTHON -m pip install -e core/ && NEXUSSY_CONFIG=$NEXUSSY_CONFIG NEXUSSY_ENV_FILE=$NEXUSSY_ENV_FILE $PYTHON -m nexussy.api.server"
}

main() {
  check_deps
  if [ "$DRY_RUN" -eq 1 ]; then dry "no files, directories, virtualenvs, PID files, env/config files, packages, or services will be created or changed"; else
  mkdir -p "$NEXUSSY_HOME" "$RUN_DIR" "$LOG_DIR" "$HOME/nexussy-projects"
  fi
  ensure_venv
  write_config_if_absent
  write_env_if_absent
  prompt_keyring
  install_packages
  write_systemd_user
  health_check
  if [ "$DRY_RUN" -eq 1 ]; then info "Dry run complete; no changes were made."; else info "Install complete. Start nexussy with: ./nexussy.sh start"; fi
}

# shellcheck disable=SC2317
if [ "${NEXUSSY_INSTALL_TEST_MODE:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

main "$@"
