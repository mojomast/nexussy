#!/usr/bin/env bash
set -u

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
NEXUSSY_HOME=${NEXUSSY_HOME:-"$HOME/.nexussy"}
NEXUSSY_CONFIG=${NEXUSSY_CONFIG:-"$NEXUSSY_HOME/nexussy.yaml"}
NEXUSSY_ENV_FILE=${NEXUSSY_ENV_FILE:-"$NEXUSSY_HOME/.env"}
RUN_DIR="$NEXUSSY_HOME/run"
VENV_DIR=${NEXUSSY_VENV:-"$NEXUSSY_HOME/venv"}
CORE_PID="$RUN_DIR/core.pid"
WEB_PID="$RUN_DIR/web.pid"
TUI_PID="$RUN_DIR/tui.pid"
CORE_LOG=${NEXUSSY_CORE_LOG:-"/tmp/nexussy-core.log"}
WEB_LOG=${NEXUSSY_WEB_LOG:-"/tmp/nexussy-web.log"}
TUI_LOG=${NEXUSSY_TUI_LOG:-"/tmp/nexussy-tui.log"}
CORE_HOST=${NEXUSSY_CORE_HOST:-"127.0.0.1"}
CORE_PORT=${NEXUSSY_CORE_PORT:-"7771"}
WEB_HOST=${NEXUSSY_WEB_HOST:-"127.0.0.1"}
WEB_PORT=${NEXUSSY_WEB_PORT:-"7772"}

info() { printf '%s\n' "[nexussy] $*"; }
warn() { printf '%s\n' "[nexussy] WARN: $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }
fail() { printf '%s\n' "[nexussy] ERROR: $*" >&2; return 1; }

python_cmd() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    printf '%s\n' "$VENV_DIR/bin/python"
    return 0
  fi
  for c in python3.13 python3.12 python3.11 python3 python; do
    if have "$c" && "$c" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    then printf '%s\n' "$c"; return 0; fi
  done
  return 1
}

ensure_runtime_python() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    printf '%s\n' "$VENV_DIR/bin/python"
    return 0
  fi
  PY=$(python_cmd) || return 1
  info "creating runtime virtual environment: $VENV_DIR" >&2
  "$PY" -m venv "$VENV_DIR" || return 1
  "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null || return 1
  info "installing runtime core/web dependencies" >&2
  (cd "$ROOT_DIR" && "$VENV_DIR/bin/python" -m pip install -e core/ -e web/) >/dev/null || return 1
  printf '%s\n' "$VENV_DIR/bin/python"
}

is_running() {
  pid_file=$1
  [ -f "$pid_file" ] || return 1
  pid=$(cat "$pid_file" 2>/dev/null || true)
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$pid" >/dev/null 2>&1
}

cleanup_stale_pid() {
  pid_file=$1
  if [ -f "$pid_file" ] && ! is_running "$pid_file"; then
    rm -f "$pid_file"
  fi
}

port_open() {
  host=$1; port=$2
  ( : > "/dev/tcp/$host/$port" ) >/dev/null 2>&1
}

health_url() { printf 'http://%s:%s/%s\n' "$1" "$2" "$3"; }

curl_ok() { curl -fsS "$1" >/dev/null 2>&1; }

wait_for_url() {
  url=$1
  i=0
  while [ "$i" -lt 30 ]; do
    curl_ok "$url" && return 0
    i=$((i + 1))
    sleep 1
  done
  return 1
}

ensure_dirs() { mkdir -p "$NEXUSSY_HOME" "$RUN_DIR" "$NEXUSSY_HOME/logs"; }

prepare_log() {
  log_file=$1
  log_dir=$(dirname -- "$log_file")
  mkdir -p "$log_dir"
  touch "$log_file" || return 1
}

start_core() {
  cleanup_stale_pid "$CORE_PID"
  if is_running "$CORE_PID"; then info "core already running"; return 0; fi
  if curl_ok "$(health_url "$CORE_HOST" "$CORE_PORT" health)"; then info "core already healthy on $CORE_HOST:$CORE_PORT (no duplicate started)"; return 0; fi
  ensure_dirs
  PYTHON=$(ensure_runtime_python) || { warn "Python 3.11+ runtime or dependency install failed"; return 1; }
  prepare_log "$CORE_LOG" || fail "cannot write core log: $CORE_LOG"
  info "starting core on $CORE_HOST:$CORE_PORT"
  old_pwd=$(pwd)
  cd "$ROOT_DIR" || return 1
  NEXUSSY_CONFIG="$NEXUSSY_CONFIG" NEXUSSY_ENV_FILE="$NEXUSSY_ENV_FILE" NEXUSSY_CORE_HOST="$CORE_HOST" NEXUSSY_CORE_PORT="$CORE_PORT" PYTHONPATH="$ROOT_DIR/core${PYTHONPATH:+:$PYTHONPATH}" nohup "$PYTHON" -m nexussy.api.server >> "$CORE_LOG" 2>&1 &
  printf '%s\n' "$!" > "$CORE_PID"
  cd "$old_pwd" || return 1
  wait_for_url "$(health_url "$CORE_HOST" "$CORE_PORT" health)" || { warn "core did not become healthy; see $CORE_LOG"; cleanup_stale_pid "$CORE_PID"; return 1; }
}

start_web() {
  cleanup_stale_pid "$WEB_PID"
  if is_running "$WEB_PID"; then info "web already running"; return 0; fi
  if curl_ok "$(health_url "$WEB_HOST" "$WEB_PORT" api/health)"; then info "web already healthy on $WEB_HOST:$WEB_PORT (no duplicate started)"; return 0; fi
  ensure_dirs
  PYTHON=$(ensure_runtime_python) || { warn "Python 3.11+ runtime or dependency install failed"; return 1; }
  prepare_log "$WEB_LOG" || fail "cannot write web log: $WEB_LOG"
  info "starting web on $WEB_HOST:$WEB_PORT"
  old_pwd=$(pwd)
  cd "$ROOT_DIR" || return 1
  NEXUSSY_CONFIG="$NEXUSSY_CONFIG" NEXUSSY_ENV_FILE="$NEXUSSY_ENV_FILE" NEXUSSY_WEB_HOST="$WEB_HOST" NEXUSSY_WEB_PORT="$WEB_PORT" NEXUSSY_CORE_HOST="$CORE_HOST" NEXUSSY_CORE_PORT="$CORE_PORT" PYTHONPATH="$ROOT_DIR/web${PYTHONPATH:+:$PYTHONPATH}" nohup "$PYTHON" -m nexussy_web.app >> "$WEB_LOG" 2>&1 &
  printf '%s\n' "$!" > "$WEB_PID"
  cd "$old_pwd" || return 1
  wait_for_url "$(health_url "$WEB_HOST" "$WEB_PORT" api/health)" || { warn "web health proxy did not become healthy; see $WEB_LOG"; cleanup_stale_pid "$WEB_PID"; return 1; }
}

start_tui() {
  curl_ok "$(health_url "$CORE_HOST" "$CORE_PORT" health)" || { warn "core health check failed; run ./nexussy.sh start first"; return 1; }
  have bun || { warn "bun not found"; return 1; }
  info "starting tui interactively; press Ctrl+C or type /quit to exit"
  old_pwd=$(pwd)
  cd "$ROOT_DIR/tui" || return 1
  bun run start
  rc=$?
  cd "$old_pwd" || return 1
  return "$rc"
}

stop_one() {
  name=$1; pid_file=$2
  if is_running "$pid_file"; then
    pid=$(cat "$pid_file")
    info "stopping $name pid $pid"
    kill "$pid" >/dev/null 2>&1 || true
    i=0
    while [ "$i" -lt 10 ] && kill -0 "$pid" >/dev/null 2>&1; do i=$((i + 1)); sleep 1; done
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
}

status() {
  cleanup_stale_pid "$CORE_PID"; cleanup_stale_pid "$WEB_PID"; cleanup_stale_pid "$TUI_PID"
  core_url=$(health_url "$CORE_HOST" "$CORE_PORT" health)
  web_url=$(health_url "$WEB_HOST" "$WEB_PORT" api/health)
  printf 'config: %s\n' "$NEXUSSY_CONFIG"
  printf 'core:  %s port=%s pid=%s health=%s\n' "$CORE_HOST" "$CORE_PORT" "$(cat "$CORE_PID" 2>/dev/null || printf '-')" "$(curl_ok "$core_url" && printf healthy || printf unavailable)"
  printf 'web:   %s port=%s pid=%s health=%s\n' "$WEB_HOST" "$WEB_PORT" "$(cat "$WEB_PID" 2>/dev/null || printf '-')" "$(curl_ok "$web_url" && printf healthy || printf unavailable)"
  printf 'tui:   pid=%s state=%s\n' "$(cat "$TUI_PID" 2>/dev/null || printf '-')" "$(is_running "$TUI_PID" && printf running || printf stopped)"
}

show_logs() {
  follow=1
  lines=80
  if [ "${1:-}" = "--no-follow" ]; then follow=0; shift; fi
  case "${1:-}" in
    core) log_file=$CORE_LOG ;;
    web) log_file=$WEB_LOG ;;
    tui) log_file=$TUI_LOG ;;
    *) printf '%s\n' "Usage: ./nexussy.sh logs [--no-follow] core|web|tui" >&2; return 2 ;;
  esac
  prepare_log "$log_file" || return 1
  if [ "$follow" -eq 1 ]; then tail -f "$log_file"; else tail -n "$lines" "$log_file"; fi
}

update() {
  PYTHON=$(python_cmd) || { warn "Python 3.11+ not found"; return 1; }
  have git || { warn "git not found"; return 1; }
  have bun || { warn "bun not found"; return 1; }
  (cd "$ROOT_DIR" && git pull) || return 1
  (cd "$ROOT_DIR" && "$PYTHON" -m pip install -e core/) || return 1
  (cd "$ROOT_DIR" && "$PYTHON" -m pip install -e web/) || return 1
  (cd "$ROOT_DIR/tui" && bun install) || return 1
}

doctor() {
  rc=0
  printf 'nexussy doctor\n'
  if PYTHON=$(python_cmd); then printf 'python: ok (%s)\n' "$PYTHON"; else printf 'python: missing Python 3.11+\n'; rc=1; fi
  if have bun; then printf 'bun: ok (%s)\n' "$(bun --version 2>/dev/null)"; else printf 'bun: missing\n'; rc=1; fi
  if have git; then printf 'git: ok\n'; else printf 'git: missing\n'; rc=1; fi
  if have curl; then printf 'curl: ok\n'; else printf 'curl: missing\n'; rc=1; fi
  if have shellcheck; then printf 'shellcheck: optional ok\n'; else printf 'shellcheck: optional missing (install shellcheck for linting)\n'; fi
  if [ -f "$NEXUSSY_CONFIG" ]; then
    printf 'config: present (%s)\n' "$NEXUSSY_CONFIG"
    missing_config=0
    for k in version home_dir projects_dir core web auth database providers stages swarm pi sse security logging cors_allow_origins core_base_url header_name global_path project_relative_path wal_enabled busy_timeout_ms write_retry_count write_retry_base_ms default_model allow_fallback request_timeout_s max_retries retry_base_ms max_iterations orchestrator_model max_workers default_worker_count worker_task_timeout_s worker_start_timeout_s file_lock_timeout_s file_lock_retry_ms merge_strategy command args startup_timeout_s shutdown_timeout_s max_stdout_line_bytes heartbeat_interval_s client_queue_max_events replay_max_events retry_ms scrub_logs reject_symlink_escape keyring_service level core_log_file web_log_file tui_log_file; do
      if ! grep -Eq "^[[:space:]]*$k:" "$NEXUSSY_CONFIG"; then missing_config=$((missing_config + 1)); fi
    done
    if [ "$missing_config" -eq 0 ]; then printf 'config keys: complete baseline\n'; else printf 'config keys: %s baseline key names not found\n' "$missing_config"; rc=1; fi
  else printf 'config: missing (%s)\n' "$NEXUSSY_CONFIG"; rc=1; fi
  printf 'core port: %s (%s, tcp=%s)\n' "$CORE_PORT" "$(curl_ok "$(health_url "$CORE_HOST" "$CORE_PORT" health)" && printf responding || printf not-responding)" "$(port_open "$CORE_HOST" "$CORE_PORT" && printf open || printf closed)"
  printf 'web port: %s (%s, tcp=%s)\n' "$WEB_PORT" "$(curl_ok "$(health_url "$WEB_HOST" "$WEB_PORT" api/health)" && printf responding || printf not-responding)" "$(port_open "$WEB_HOST" "$WEB_PORT" && printf open || printf closed)"
  if have "${NEXUSSY_PI_COMMAND:-pi}"; then
    printf 'pi command: ok (%s)\n' "${NEXUSSY_PI_COMMAND:-pi}"
  elif PY=$(python_cmd) && PYTHONPATH="$ROOT_DIR/core${PYTHONPATH:+:$PYTHONPATH}" "$PY" - <<'PY' >/dev/null 2>&1
import nexussy.swarm.local_pi_worker
PY
  then
    printf 'pi command: external missing; bundled nexussy Pi-compatible fallback available\n'
  else
    printf 'pi command: missing (install Pi CLI or set NEXUSSY_PI_COMMAND)\n'
  fi
  keys="OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GROQ_API_KEY GEMINI_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY FIREWORKS_API_KEY XAI_API_KEY GLM_API_KEY ZAI_API_KEY REQUESTY_API_KEY AETHER_API_KEY OLLAMA_BASE_URL"
  configured=0
  for k in $keys; do
    v=${!k-}
    if [ -z "$v" ] && [ -f "$NEXUSSY_ENV_FILE" ]; then
      while IFS= read -r line; do
        case "$line" in "$k="*) v=${line#*=}; break ;; esac
      done < "$NEXUSSY_ENV_FILE"
    fi
    if [ -n "$v" ]; then configured=$((configured + 1)); fi
  done
  if [ "$configured" -gt 0 ]; then printf 'provider keys: %s configured in environment/env file\n' "$configured"; else printf 'provider keys: none configured (mock mode only; fill %s or use keyring for production providers)\n' "$NEXUSSY_ENV_FILE"; fi
  return "$rc"
}

usage() {
  cat <<'USAGE'
Usage: ./nexussy.sh start|start-tui|stop|status|logs [--no-follow] core|web|tui|update|doctor
USAGE
}

# shellcheck disable=SC2317
if [ "${NEXUSSY_SH_TEST_MODE:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

cmd=${1:-}
case "$cmd" in
  start) start_core && start_web ;;
  start-tui) start_tui ;;
  stop) stop_one tui "$TUI_PID"; stop_one web "$WEB_PID"; stop_one core "$CORE_PID" ;;
  status) status ;;
  logs) shift; show_logs "${1:-}" ;;
  update) update ;;
  doctor) doctor ;;
  -h|--help|help|'') usage ;;
  *) printf '%s\n' "Unknown command: $cmd" >&2; usage >&2; exit 2 ;;
esac
