#!/usr/bin/env bash
set -u

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
NEXUSSY_SMOKE_LIBRARY=1 . "$ROOT_DIR/scripts/smoke_integration.sh"

TMP_DIR=${TMPDIR:-/tmp}/nexussy-smoke-parser.$$
STREAM_FILE="$TMP_DIR/stream.sse"

fail() { printf 'PARSER FAIL: %s\n' "$*" >&2; exit 1; }
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT INT TERM
mkdir -p "$TMP_DIR" || fail "could not create temp directory"

cat >"$STREAM_FILE" <<'SSE'
id: evt-run
event: run_started
retry: 30000
data: {"type":"run_started","payload":{"session_id":"session-123","run_id":"run-123"}}

id: evt-done
event: done
retry: 30000
data: {"type":"done","payload":{"final_status":"passed","summary":"ok"}}

SSE

session_id=$(sse_event_value "$STREAM_FILE" run_started session_id || true)
final_status=$(sse_event_value "$STREAM_FILE" done final_status || true)

[ "$session_id" = "session-123" ] || fail "expected session-123, got ${session_id:-empty}"
[ "$final_status" = "passed" ] || fail "expected passed, got ${final_status:-empty}"
printf 'PARSER PASS\n'
