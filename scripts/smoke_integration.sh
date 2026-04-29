#!/usr/bin/env bash
# Usage: NEXUSSY_SMOKE_PROJECT_DIR=/path/to/repo NEXUSSY_PI_COMMAND=/path/to/pi ./scripts/smoke_integration.sh
set -u

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
API_BASE=${NEXUSSY_SMOKE_API_BASE:-http://127.0.0.1:7772/api}
TMP_DIR=${TMPDIR:-/tmp}/nexussy-smoke.$$
STREAM_FILE="$TMP_DIR/stream.sse"

fail() { printf 'SMOKE FAIL: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"; }
json_get() { python3 -c 'import json,sys; data=json.load(sys.stdin); cur=data; [cur := (cur.get(p) if isinstance(cur, dict) else None) for p in sys.argv[1].split(".") if p]; print("" if cur is None else cur)' "$1"; }

cleanup() {
  if [ -n "${CURL_PID:-}" ]; then kill "$CURL_PID" >/dev/null 2>&1 || true; fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM
mkdir -p "$TMP_DIR" || fail "could not create temp directory"

need curl
need python3
[ -n "${NEXUSSY_SMOKE_PROJECT_DIR:-}" ] || fail "NEXUSSY_SMOKE_PROJECT_DIR is required"
[ -d "$NEXUSSY_SMOKE_PROJECT_DIR" ] || fail "NEXUSSY_SMOKE_PROJECT_DIR does not exist"
git -C "$NEXUSSY_SMOKE_PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1 || fail "NEXUSSY_SMOKE_PROJECT_DIR must be a git repo"
[ -n "${NEXUSSY_PI_COMMAND:-}" ] || fail "NEXUSSY_PI_COMMAND is required"
$NEXUSSY_PI_COMMAND --version >/dev/null 2>&1 || fail "NEXUSSY_PI_COMMAND --version failed"
"$ROOT_DIR/nexussy.sh" doctor >/dev/null 2>&1 || fail "nexussy.sh doctor failed; configure provider credentials first"
curl -fsS "$API_BASE/health" >/dev/null 2>&1 || fail "server health check failed. Start server with: ./nexussy.sh start"

start_body=$(python3 -c 'import json,os,time; print(json.dumps({"project_name":"smoke-%d" % time.time(),"description":"Add a hello_smoke.txt file with content '\''smoke ok'\''","existing_repo_path":os.environ["NEXUSSY_SMOKE_PROJECT_DIR"],"auto_approve_interview":True,"metadata":{"pi_command":os.environ["NEXUSSY_PI_COMMAND"]}}))')
start_response=$(curl -fsS -H 'content-type: application/json' -d "$start_body" "$API_BASE/pipeline/start") || fail "pipeline start request failed"
run_id=$(printf '%s' "$start_response" | json_get run_id)
session_id=$(printf '%s' "$start_response" | json_get session_id)
[ -n "$run_id" ] || fail "pipeline start response missing run_id"
[ -n "$session_id" ] || fail "pipeline start response missing session_id"

curl --no-buffer -N -fsS "$API_BASE/pipeline/runs/$run_id/stream" >"$STREAM_FILE" 2>"$TMP_DIR/curl.err" & CURL_PID=$!
deadline=$((SECONDS + 180))
while [ "$SECONDS" -lt "$deadline" ]; do
  if grep -q '^event: done' "$STREAM_FILE" 2>/dev/null; then break; fi
  if ! kill -0 "$CURL_PID" >/dev/null 2>&1 && ! grep -q '^event: done' "$STREAM_FILE" 2>/dev/null; then fail "stream ended before done event for run_id=$run_id"; fi
  sleep 1
done
grep -q '^event: done' "$STREAM_FILE" 2>/dev/null || fail "pipeline did not complete in 180s run_id=$run_id"
kill "$CURL_PID" >/dev/null 2>&1 || true; CURL_PID=""

python3 - "$STREAM_FILE" <<'PY' || fail "done event final_status was not passed"
import json, sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for i, line in enumerate(lines):
    if line == "event: done":
        data = json.loads(lines[i + 1].split("data: ", 1)[1])
        status = data.get("payload", {}).get("final_status")
        if status == "passed":
            raise SystemExit(0)
raise SystemExit(1)
PY

changed=$(curl -fsS "$API_BASE/pipeline/artifacts/changed_files?session_id=$session_id") || fail "changed_files artifact request failed"
develop=$(curl -fsS "$API_BASE/pipeline/artifacts/develop_report?session_id=$session_id") || fail "develop_report artifact request failed"
merge=$(curl -fsS "$API_BASE/pipeline/artifacts/merge_report?session_id=$session_id") || fail "merge_report artifact request failed"
printf '%s' "$changed" | python3 -c 'import json,sys; body=json.load(sys.stdin); data=json.loads(body.get("content_text") or "{}"); assert len(data.get("changed_files", [])) >= 1' || fail "changed_files had no entries"
printf '%s' "$develop" | python3 -c 'import json,sys; body=json.load(sys.stdin); data=json.loads(body.get("content_text") or "{}"); assert data.get("passed") is True' || fail "develop_report.passed was not true"
printf '%s' "$merge" | python3 -c 'import json,sys; body=json.load(sys.stdin); data=json.loads(body.get("content_text") or "{}"); assert data.get("passed") is True' || fail "merge_report.passed was not true"

status=$(curl -fsS "$API_BASE/pipeline/status?run_id=$run_id") || fail "status request failed"
printf '%s' "$status" >"$TMP_DIR/status.json"
printf '%s' "$changed" >"$TMP_DIR/changed.json"
python3 - "$run_id" "$session_id" "$TMP_DIR/status.json" "$TMP_DIR/changed.json" <<'PY'
import json, sys
status = json.load(open(sys.argv[3], encoding="utf-8"))
changed = json.loads(json.load(open(sys.argv[4], encoding="utf-8")).get("content_text") or "{}")
root = status.get("status", status)
run = root.get("run", {})
stages = root.get("stages") or root.get("stage_statuses") or []
print("field\tvalue")
print(f"run_id\t{sys.argv[1]}")
print(f"session_id\t{sys.argv[2]}")
for stage in stages:
    name = stage.get("stage") or stage.get("name")
    start = stage.get("started_at")
    finish = stage.get("finished_at")
    print(f"stage:{name}\t{start or '-'}..{finish or '-'}")
print(f"changed_files\t{len(changed.get('changed_files', []))}")
usage = run.get("usage") or root.get("usage") or {}
print(f"total_cost_usd\t{usage.get('cost_usd', 0)}")
PY
printf 'SMOKE PASS\n'
