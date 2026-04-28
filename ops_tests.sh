#!/usr/bin/env bash
set -u

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TMP_ROOT=${TMPDIR:-/tmp}/nexussy-ops-tests.$$
FAILURES=0

pass() { printf 'ok - %s\n' "$*"; }
fail() { printf 'not ok - %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
assert_file() { [ -e "$1" ] && pass "$2" || fail "$2"; }
assert_no_file() { [ ! -e "$1" ] && pass "$2" || fail "$2"; }
assert_contains() { case "$1" in *"$2"*) pass "$3" ;; *) fail "$3" ;; esac; }

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

# Source launcher functions to exercise duplicate-start and stale-PID branches
# without starting core/web or touching system services.
RUN_HOME="$TMP_ROOT/run-home"
mkdir -p "$RUN_HOME/run" "$RUN_HOME/logs" || exit 1
(
  export NEXUSSY_SH_TEST_MODE=1 NEXUSSY_HOME="$RUN_HOME" NEXUSSY_CONFIG="$RUN_HOME/nexussy.yaml" NEXUSSY_ENV_FILE="$RUN_HOME/.env"
  export NEXUSSY_CORE_LOG="$RUN_HOME/logs/core.log" NEXUSSY_WEB_LOG="$RUN_HOME/logs/web.log" NEXUSSY_TUI_LOG="$RUN_HOME/logs/tui.log"
  # shellcheck source=nexussy.sh
  . "$ROOT_DIR/nexussy.sh"
  sleep 60 & SLEEP_PID=$!
  printf '%s\n' "$SLEEP_PID" > "$CORE_PID"
  start_core >/tmp/nexussy-ops-start-core.$$ 2>&1
  printf '999999\n' > "$WEB_PID"
  cleanup_stale_pid "$WEB_PID"
  printf 'core log line\n' > "$CORE_LOG"
  show_logs --no-follow core >/tmp/nexussy-ops-logs.$$ 2>&1
  doctor >/tmp/nexussy-ops-doctor.$$ 2>&1 || true
  kill "$SLEEP_PID" >/dev/null 2>&1 || true
)
start_text=$(tr '\n' ' ' < /tmp/nexussy-ops-start-core.$$ 2>/dev/null || true)
logs_text=$(tr '\n' ' ' < /tmp/nexussy-ops-logs.$$ 2>/dev/null || true)
doctor_text=$(tr '\n' ' ' < /tmp/nexussy-ops-doctor.$$ 2>/dev/null || true)
assert_contains "$start_text" "core already running" "duplicate core start does not spawn"
assert_no_file "$RUN_HOME/run/web.pid" "stale PID cleanup removes dead PID"
assert_contains "$logs_text" "core log line" "logs --no-follow prints log contents"
assert_contains "$doctor_text" "nexussy doctor" "doctor prints diagnostics header"
assert_contains "$doctor_text" "provider keys" "doctor reports provider key readiness"
rm -f /tmp/nexussy-ops-start-core.$$ /tmp/nexussy-ops-logs.$$ /tmp/nexussy-ops-doctor.$$

if [ "$FAILURES" -eq 0 ]; then
  printf 'ops tests passed\n'
  exit 0
fi
printf 'ops tests failed: %s\n' "$FAILURES" >&2
exit 1
