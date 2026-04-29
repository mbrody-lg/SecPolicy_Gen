#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STACK_STARTED=0
READINESS_TIMEOUT_SECONDS="${READINESS_TIMEOUT_SECONDS:-120}"
READINESS_INTERVAL_SECONDS="${READINESS_INTERVAL_SECONDS:-2}"
DOCKER_COMPOSE_CMD=()

wait_for_ready() {
  local label=$1
  local url=$2
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
  return 1
}

cleanup() {
  if [[ "$STACK_STARTED" -eq 1 ]]; then
    "${DOCKER_COMPOSE_CMD[@]}" -f infrastructure/docker-compose.yml --env-file infrastructure/.env down >/dev/null
  fi
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

echo "[critical-path] starting docker stack"
make docker-preflight
read -r -a DOCKER_COMPOSE_CMD <<< "$(scripts/docker_preflight.sh --print-compose)"
"${DOCKER_COMPOSE_CMD[@]}" -f infrastructure/docker-compose.yml --env-file infrastructure/.env up --build -d
STACK_STARTED=1

echo "[critical-path] waiting for readiness probes on all services (${READINESS_TIMEOUT_SECONDS}s timeout, ${READINESS_INTERVAL_SECONDS}s interval)"
wait_for_ready "context-agent" "http://localhost:5003/ready"
wait_for_ready "policy-agent" "http://localhost:5002/ready"
wait_for_ready "validator-agent" "http://localhost:5001/ready"

echo "[critical-path] running service suites"
make context-tests
make policy-tests
make validator-tests

echo "[critical-path] resetting stack before smoke validation"
"${DOCKER_COMPOSE_CMD[@]}" -f infrastructure/docker-compose.yml --env-file infrastructure/.env down >/dev/null
STACK_STARTED=0

echo "[critical-path] running end-to-end functional smoke with observability checks"
make functional-smoke

echo "[critical-path] validation completed"
