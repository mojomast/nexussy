#!/usr/bin/env bash
# shellcheck disable=SC2015,SC2030,SC2031,SC2329
set -u

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
TMP_ROOT=${TMPDIR:-/tmp}/nexussy-ops-tests.$$
FAILURES=0

pass() { printf 'ok - %s\n' "$*"; }
fail() { printf 'not ok - %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
assert_file() { [ -e "$1" ] && pass "$2" || fail "$2"; }
assert_no_file() { [ ! -e "$1" ] && pass "$2" || fail "$2"; }
assert_contains() { case "$1" in *"$2"*) pass "$3" ;; *) fail "$3" ;; esac; }
assert_not_contains() { case "$1" in *"$2"*) fail "$3" ;; *) pass "$3" ;; esac; }

mkdir -p "$TMP_ROOT" || exit 1
cleanup() {
  if [ -n "${SLEEP_PID:-}" ]; then kill "$SLEEP_PID" >/dev/null 2>&1 || true; fi
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT INT TERM

# Dry-run must not create the requested home/config/env/run/log paths.
DRY_HOME="$TMP_ROOT/dry-home"
dry_out=$(NEXUSSY_HOME="$DRY_HOME" "$ROOT_DIR/install.sh" --non-interactive --dry-run 2>&1)
dry_rc=$?
[ "$dry_rc" -eq 0 ] && pass "dry-run exits successfully" || fail "dry-run exits successfully"
assert_contains "$dry_out" "no changes were made" "dry-run reports no writes"
assert_no_file "$DRY_HOME" "dry-run creates no NEXUSSY_HOME"

# Source installer functions in an isolated shell context to prove generated
# config/env are idempotent and preserve user edits on rerun.
CFG_HOME="$TMP_ROOT/cfg-home"
mkdir -p "$CFG_HOME" || exit 1
(
  export NEXUSSY_INSTALL_TEST_MODE=1 NEXUSSY_HOME="$CFG_HOME" NEXUSSY_CONFIG="$CFG_HOME/nexussy.yaml" NEXUSSY_ENV_FILE="$CFG_HOME/.env"
  # shellcheck source=install.sh
  . "$ROOT_DIR/install.sh"
  write_config_if_absent
  write_env_if_absent
  printf '\n# user edit\n' >> "$NEXUSSY_CONFIG"
  printf '\nUSER_SENTINEL=kept\n' >> "$NEXUSSY_ENV_FILE"
  write_config_if_absent
  write_env_if_absent
)
assert_file "$CFG_HOME/nexussy.yaml" "config generated"
assert_file "$CFG_HOME/.env" "env generated"
cfg_text=$(tr '\n' ' ' < "$CFG_HOME/nexussy.yaml")
env_text=$(tr '\n' ' ' < "$CFG_HOME/.env")
assert_contains "$cfg_text" "# user edit" "config rerun preserves edits"
assert_contains "$env_text" "USER_SENTINEL=kept" "env rerun preserves edits"

# Systemd user units are generated only for --systemd-user and reruns preserve
# local edits instead of overwriting operator customizations.
SYSTEMD_HOME="$TMP_ROOT/systemd-home"
mkdir -p "$SYSTEMD_HOME" || exit 1
(
  export NEXUSSY_INSTALL_TEST_MODE=1 HOME="$SYSTEMD_HOME" NEXUSSY_HOME="$SYSTEMD_HOME/.nexussy"
  export NEXUSSY_CONFIG="$SYSTEMD_HOME/.nexussy/nexussy.yaml" NEXUSSY_ENV_FILE="$SYSTEMD_HOME/.nexussy/.env"
  # shellcheck source=install.sh
  . "$ROOT_DIR/install.sh"
  SYSTEMD_USER=1
  DRY_RUN=0
  PYTHON=$(command -v python3 || command -v python)
  write_systemd_user
  printf '\n# local core edit\n' >> "$HOME/.config/systemd/user/nexussy-core.service"
  printf '\n# local web edit\n' >> "$HOME/.config/systemd/user/nexussy-web.service"
  write_systemd_user
)
core_unit="$SYSTEMD_HOME/.config/systemd/user/nexussy-core.service"
web_unit="$SYSTEMD_HOME/.config/systemd/user/nexussy-web.service"
assert_file "$core_unit" "systemd core unit generated"
assert_file "$web_unit" "systemd web unit generated"
core_unit_text=$(tr '\n' ' ' < "$core_unit")
web_unit_text=$(tr '\n' ' ' < "$web_unit")
assert_contains "$core_unit_text" "ExecStart=" "systemd core unit has ExecStart"
assert_contains "$core_unit_text" "-m nexussy.api.server" "systemd core unit starts core module"
assert_contains "$web_unit_text" "-m nexussy_web.app" "systemd web unit starts web module"
assert_contains "$core_unit_text" "# local core edit" "systemd core rerun preserves edits"
assert_contains "$web_unit_text" "# local web edit" "systemd web rerun preserves edits"

# Source launcher functions to exercise duplicate-start and stale-PID branches
# without starting core/web or touching system services.
RUN_HOME="$TMP_ROOT/run-home"
mkdir -p "$RUN_HOME/run" "$RUN_HOME/logs" || exit 1
(
  export NEXUSSY_SH_TEST_MODE=1 NEXUSSY_HOME="$RUN_HOME" NEXUSSY_CONFIG="$RUN_HOME/nexussy.yaml" NEXUSSY_ENV_FILE="$RUN_HOME/.env"
  export NEXUSSY_CORE_LOG="$RUN_HOME/logs/core.log" NEXUSSY_WEB_LOG="$RUN_HOME/logs/web.log" NEXUSSY_TUI_LOG="$RUN_HOME/logs/tui.log"
  # shellcheck source=nexussy.sh
  . "$ROOT_DIR/nexussy.sh"
  curl_ok() { return 0; }
  sleep 60 & SLEEP_PID=$!
  printf '%s\n' "$SLEEP_PID" > /tmp/nexussy-ops-sleep-pid.$$
  printf '%s\n' "$SLEEP_PID" > "$CORE_PID"
  printf '%s\n' "$SLEEP_PID" > "$WEB_PID"
  start_core >/tmp/nexussy-ops-start-core.$$ 2>&1
  status >/tmp/nexussy-ops-status.$$ 2>&1
  printf '999999\n' > "$WEB_PID"
  cleanup_stale_pid "$WEB_PID"
  printf 'core log line\n' > "$CORE_LOG"
  show_logs --no-follow core >/tmp/nexussy-ops-logs.$$ 2>&1
  export NEXUSSY_PI_COMMAND="nexussy-missing-pi-command-$$"
  unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GROQ_API_KEY GEMINI_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY FIREWORKS_API_KEY XAI_API_KEY GLM_API_KEY ZAI_API_KEY REQUESTY_API_KEY AETHER_API_KEY OLLAMA_BASE_URL
  python_cmd() { return 1; }
  doctor >/tmp/nexussy-ops-doctor.$$ 2>&1 || true
  kill "$SLEEP_PID" >/dev/null 2>&1 || true
)
start_text=$(tr '\n' ' ' < /tmp/nexussy-ops-start-core.$$ 2>/dev/null || true)
status_text=$(tr '\n' ' ' < /tmp/nexussy-ops-status.$$ 2>/dev/null || true)
logs_text=$(tr '\n' ' ' < /tmp/nexussy-ops-logs.$$ 2>/dev/null || true)
doctor_text=$(tr '\n' ' ' < /tmp/nexussy-ops-doctor.$$ 2>/dev/null || true)
sleep_pid=$(cat /tmp/nexussy-ops-sleep-pid.$$ 2>/dev/null || true)
assert_contains "$start_text" "core already running" "duplicate core start does not spawn"
assert_contains "$status_text" "config: $RUN_HOME/nexussy.yaml" "status reports config path"
assert_contains "$status_text" "core:  127.0.0.1 port=7771 pid=$sleep_pid health=healthy" "status reports core port pid health"
assert_contains "$status_text" "web:   127.0.0.1 port=7772 pid=$sleep_pid health=healthy" "status reports web port pid health"
assert_contains "$status_text" "tui:   pid=- state=stopped" "status reports tui pid state"
assert_no_file "$RUN_HOME/run/web.pid" "stale PID cleanup removes dead PID"
assert_contains "$logs_text" "core log line" "logs --no-follow prints log contents"
assert_contains "$doctor_text" "nexussy doctor" "doctor prints diagnostics header"
assert_contains "$doctor_text" "pi command: missing (install Pi CLI or set NEXUSSY_PI_COMMAND)" "doctor reports missing Pi command remediation"
assert_contains "$doctor_text" "provider keys" "doctor reports provider key readiness"
assert_contains "$doctor_text" "mock mode only" "doctor explains missing provider key behavior"
rm -f /tmp/nexussy-ops-start-core.$$ /tmp/nexussy-ops-status.$$ /tmp/nexussy-ops-logs.$$ /tmp/nexussy-ops-doctor.$$ /tmp/nexussy-ops-sleep-pid.$$

# Exercise start-tui and update command wiring with fake tools so no real TUI,
# git pull, package install, or service process is launched.
FAKE_BIN="$TMP_ROOT/fake-bin"
LAUNCH_HOME="$TMP_ROOT/launcher-home"
mkdir -p "$FAKE_BIN" "$LAUNCH_HOME/run" "$LAUNCH_HOME/logs" || exit 1
cat > "$FAKE_BIN/bun" <<'SH'
#!/usr/bin/env bash
printf 'bun:%s:%s\n' "$PWD" "$*" >> "$NEXUSSY_FAKE_TOOL_LOG"
if [ "${1:-}" = "--version" ]; then printf '1.2.0\n'; fi
SH
cat > "$FAKE_BIN/git" <<'SH'
#!/usr/bin/env bash
printf 'git:%s:%s\n' "$PWD" "$*" >> "$NEXUSSY_FAKE_TOOL_LOG"
SH
cat > "$FAKE_BIN/python3" <<'SH'
#!/usr/bin/env bash
printf 'python:%s:%s\n' "$PWD" "$*" >> "$NEXUSSY_FAKE_TOOL_LOG"
SH
chmod +x "$FAKE_BIN/bun" "$FAKE_BIN/git" "$FAKE_BIN/python3"
(
  export NEXUSSY_SH_TEST_MODE=1 NEXUSSY_HOME="$LAUNCH_HOME" NEXUSSY_CONFIG="$LAUNCH_HOME/nexussy.yaml" NEXUSSY_ENV_FILE="$LAUNCH_HOME/.env"
  export NEXUSSY_FAKE_TOOL_LOG="$LAUNCH_HOME/tool.log" PATH="$FAKE_BIN:$PATH"
  # shellcheck source=nexussy.sh
  . "$ROOT_DIR/nexussy.sh"
  curl_ok() { return 0; }
  python_cmd() { printf '%s\n' "$FAKE_BIN/python3"; }
  start_tui >/tmp/nexussy-ops-start-tui.$$ 2>&1
  update >/tmp/nexussy-ops-update.$$ 2>&1
)
tool_text=$(tr '\n' ' ' < "$LAUNCH_HOME/tool.log" 2>/dev/null || true)
start_tui_text=$(tr '\n' ' ' < /tmp/nexussy-ops-start-tui.$$ 2>/dev/null || true)
assert_contains "$start_tui_text" "starting tui interactively" "start-tui verifies core and starts TUI command"
assert_contains "$tool_text" "bun:$ROOT_DIR/tui:run start" "start-tui runs bun start from tui directory"
assert_contains "$tool_text" "git:$ROOT_DIR:pull" "update runs git pull from repo root"
assert_contains "$tool_text" "python:$ROOT_DIR:-m pip install -e core/" "update reinstalls core"
assert_contains "$tool_text" "python:$ROOT_DIR:-m pip install -e web/" "update reinstalls web"
assert_contains "$tool_text" "bun:$ROOT_DIR/tui:install" "update runs bun install from tui directory"
rm -f /tmp/nexussy-ops-start-tui.$$ /tmp/nexussy-ops-update.$$

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$ROOT_DIR/install.sh" "$ROOT_DIR/nexussy.sh" "$ROOT_DIR/ops_tests.sh" "$ROOT_DIR/launch_verify.sh" && pass "shellcheck passes" || fail "shellcheck passes"
else
  pass "shellcheck unavailable; lint remains blocked-external"
fi

if [ "$FAILURES" -eq 0 ]; then
  printf 'ops tests passed\n'
  exit 0
fi
printf 'ops tests failed: %s\n' "$FAILURES" >&2
exit 1
