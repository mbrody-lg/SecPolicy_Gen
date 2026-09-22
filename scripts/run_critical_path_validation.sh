#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/redaction.sh"

STACK_STARTED=0
READINESS_TIMEOUT_SECONDS="${READINESS_TIMEOUT_SECONDS:-120}"
READINESS_INTERVAL_SECONDS="${READINESS_INTERVAL_SECONDS:-2}"
DOCKER_COMPOSE_CMD=()
LOG_TAIL_LINES="${LOG_TAIL_LINES:-80}"
ENV_FILE="${CRITICAL_PATH_ENV_FILE:-infrastructure/.env}"
COMPOSE_OVERRIDE="${CRITICAL_PATH_COMPOSE_OVERRIDE:-}"
COMPOSE_PROJECT_NAME="${CRITICAL_PATH_COMPOSE_PROJECT:-}"
REMOVE_VOLUMES="${CRITICAL_PATH_REMOVE_VOLUMES:-0}"
COMPOSE_ARGS=(-f infrastructure/docker-compose.yml --env-file "$ENV_FILE")
if [[ -n "$COMPOSE_OVERRIDE" ]]; then
  COMPOSE_ARGS=(-f infrastructure/docker-compose.yml -f "$COMPOSE_OVERRIDE" --env-file "$ENV_FILE")
fi

collect_readiness_diagnostics() {
  local label=$1
  local url=$2
  local compose_service=$3

  echo "[critical-path] diagnostics for $label readiness failure" >&2
  echo "[critical-path] readiness response from $url:" >&2
  curl -sS "$url" 2>&1 | redact_sensitive_output >&2 || true
  echo >&2

  if [[ "${#DOCKER_COMPOSE_CMD[@]}" -gt 0 ]]; then
    echo "[critical-path] compose status:" >&2
    "${DOCKER_COMPOSE_CMD[@]}" "${COMPOSE_ARGS[@]}" ps 2>&1 \
      | redact_sensitive_output >&2 || true
    echo "[critical-path] recent $compose_service logs (tail=$LOG_TAIL_LINES):" >&2
    "${DOCKER_COMPOSE_CMD[@]}" "${COMPOSE_ARGS[@]}" logs --tail "$LOG_TAIL_LINES" "$compose_service" 2>&1 \
      | redact_sensitive_output >&2 || true
  fi
}

wait_for_ready() {
  local label=$1
  local url=$2
  local compose_service=$3
  local elapsed=0
  local code=""

  while (( elapsed < READINESS_TIMEOUT_SECONDS )); do
    code="$(curl -sS -o /dev/null -w "%{http_code}" "$url" || echo 000)"
    if [[ "$code" == "200" ]]; then
      echo "[critical-path] $label ready"
      return 0
    fi
    sleep "$READINESS_INTERVAL_SECONDS"
    elapsed=$((elapsed + READINESS_INTERVAL_SECONDS))
  done

  echo "[critical-path] timeout waiting ${READINESS_TIMEOUT_SECONDS}s for $label readiness at $url; last HTTP status: $code" >&2
  echo "[critical-path] try increasing READINESS_TIMEOUT_SECONDS, inspect 'make logs', or run 'make docker-preflight' to verify Docker prerequisites." >&2
  collect_readiness_diagnostics "$label" "$url" "$compose_service"
  return 1
}

cleanup() {
  if [[ "$STACK_STARTED" -eq 1 ]]; then
    compose_down
  fi
}

compose_down() {
  local down_args=(down --remove-orphans)
  if [[ "$REMOVE_VOLUMES" == "1" || "$REMOVE_VOLUMES" == "true" ]]; then
    down_args+=( -v )
  fi
  "${DOCKER_COMPOSE_CMD[@]}" "${COMPOSE_ARGS[@]}" "${down_args[@]}" >/dev/null
}

trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for critical path validation." >&2
  exit 1
fi

if ! [[ "$READINESS_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( READINESS_TIMEOUT_SECONDS <= 0 )); then
  echo "READINESS_TIMEOUT_SECONDS must be a positive integer number of seconds." >&2
  exit 1
fi

if ! [[ "$READINESS_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || (( READINESS_INTERVAL_SECONDS <= 0 )); then
  echo "READINESS_INTERVAL_SECONDS must be a positive integer number of seconds." >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Critical-path environment file does not exist: $ENV_FILE" >&2
  exit 1
fi
if [[ -n "$COMPOSE_OVERRIDE" && ! -f "$COMPOSE_OVERRIDE" ]]; then
  echo "Critical-path Compose override does not exist: $COMPOSE_OVERRIDE" >&2
  exit 1
fi

echo "[critical-path] starting docker stack"
make docker-preflight
read -r -a DOCKER_COMPOSE_CMD <<< "$(scripts/docker_preflight.sh --print-compose)"
if [[ -n "$COMPOSE_PROJECT_NAME" ]]; then
  DOCKER_COMPOSE_CMD+=( -p "$COMPOSE_PROJECT_NAME" )
fi
"${DOCKER_COMPOSE_CMD[@]}" "${COMPOSE_ARGS[@]}" up --build -d
STACK_STARTED=1

echo "[critical-path] waiting for readiness probes on all services (${READINESS_TIMEOUT_SECONDS}s timeout, ${READINESS_INTERVAL_SECONDS}s interval)"
wait_for_ready "context-agent" "http://localhost:5003/ready" "context-agent"
wait_for_ready "policy-agent" "http://localhost:5002/ready" "policy-agent"
wait_for_ready "validator-agent" "http://localhost:5001/ready" "validator-agent"

echo "[critical-path] running service suites"
make context-tests
make context-evals
CONTEXT_BROWSER_ENV_FILE="$ENV_FILE" \
CONTEXT_BROWSER_COMPOSE_PROJECT="$COMPOSE_PROJECT_NAME" \
CONTEXT_BROWSER_COMPOSE_OVERRIDE="$COMPOSE_OVERRIDE" \
  make context-browser-smoke
make policy-tests
make validator-tests
make governance-tests

echo "[critical-path] resetting stack before smoke validation"
compose_down
STACK_STARTED=0

echo "[critical-path] running end-to-end functional smoke with observability checks"
MIGRATION_SMOKE_ENV_FILE="$ENV_FILE" \
MIGRATION_SMOKE_COMPOSE_PROJECT="$COMPOSE_PROJECT_NAME" \
MIGRATION_SMOKE_COMPOSE_OVERRIDE="$COMPOSE_OVERRIDE" \
  make functional-smoke

echo "[critical-path] validation completed"
