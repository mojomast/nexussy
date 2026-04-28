#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
CORE_HOST=${NEXUSSY_CORE_HOST:-"127.0.0.1"}
CORE_PORT=${NEXUSSY_CORE_PORT:-"7771"}
WEB_HOST=${NEXUSSY_WEB_HOST:-"127.0.0.1"}
WEB_PORT=${NEXUSSY_WEB_PORT:-"7772"}
CORE_URL="http://$CORE_HOST:$CORE_PORT/health"
WEB_URL="http://$WEB_HOST:$WEB_PORT/api/health"

info() { printf '%s\n' "[launch] $*"; }
warn() { printf '%s\n' "[launch] WARN: $*" >&2; }
fail() { printf '%s\n' "[launch] ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

curl_ok() { curl -fsS "$1" >/dev/null 2>&1; }

wait_for_url() {
  label="$1"
  url="$2"
  info "waiting for $label: $url"
  i=0
  while [ "$i" -lt 30 ]; do
    if curl_ok "$url"; then
      printf '\n'
      info "$label healthy: $url"
      return 0
    fi
    printf '.'
    i=$((i + 1))
    sleep 1
  done
  printf '\n'
  return 1
}

configured_provider_count() {
  keys="OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GROQ_API_KEY GEMINI_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY FIREWORKS_API_KEY XAI_API_KEY GLM_API_KEY ZAI_API_KEY REQUESTY_API_KEY AETHER_API_KEY OLLAMA_BASE_URL"
  env_file=${NEXUSSY_ENV_FILE:-"$HOME/.nexussy/.env"}
  count=0
  for key in $keys; do
    value=${!key-}
    if [ -z "$value" ] && [ -f "$env_file" ]; then
      while IFS= read -r line; do
        case "$line" in "$key="*) value=${line#*=}; break ;; esac
      done < "$env_file"
    fi
    if [ -n "$value" ]; then count=$((count + 1)); fi
  done
  printf '%s\n' "$count"
}

cd "$ROOT_DIR" || fail "cannot enter $ROOT_DIR"
have curl || fail "curl is required"

info "starting nexussy core and web"
./nexussy.sh start || fail "./nexussy.sh start failed"

wait_for_url core "$CORE_URL" || {
  warn "core did not become healthy"
  warn "recent core log: ./nexussy.sh logs --no-follow core"
  exit 1
}

wait_for_url web "$WEB_URL" || {
  warn "web did not become healthy"
  warn "recent web log: ./nexussy.sh logs --no-follow web"
  exit 1
}

providers=$(configured_provider_count)
if [ "$providers" -gt 0 ]; then
  info "provider keys configured: $providers"
else
  warn "no provider keys configured; run: cd tui && bun run start -- --setup"
fi

info "status summary"
./nexussy.sh status

cat <<EOF

Launch verified.

Start the TUI in this terminal with:
  ./nexussy.sh start-tui

The TUI stays open. Type /secrets to verify provider keys, or /quit to exit.

Useful follow-up commands:
  ./nexussy.sh doctor
  ./nexussy.sh logs --no-follow core
  ./nexussy.sh logs --no-follow web
  ./nexussy.sh stop

EOF
