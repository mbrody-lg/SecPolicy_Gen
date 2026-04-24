#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STACK_STARTED=0

wait_for_ready() {
  local label=$1
  local url=$2
  local attempts=0
  local max_attempts=60

  while (( attempts < max_attempts )); do
    if [[ "$(curl -sS -o /dev/null -w "%{http_code}" "$url" || echo 000)" == "200" ]]; then
      echo "[critical-path] $label ready"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 2
  done

  echo "[critical-path] timeout waiting for $label readiness at $url" >&2
  return 1
}

cleanup() {
  if [[ "$STACK_STARTED" -eq 1 ]]; then
    make down >/dev/null
  fi
}

trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for critical path validation." >&2
  exit 1
fi

echo "[critical-path] starting docker stack"
make up
STACK_STARTED=1

echo "[critical-path] waiting for readiness probes on all services"
wait_for_ready "context-agent" "http://localhost:5003/ready"
wait_for_ready "policy-agent" "http://localhost:5002/ready"
wait_for_ready "validator-agent" "http://localhost:5001/ready"

echo "[critical-path] running service suites"
make context-tests
make policy-tests
make validator-tests

echo "[critical-path] resetting stack before smoke validation"
make down >/dev/null
STACK_STARTED=0

echo "[critical-path] running end-to-end functional smoke with observability checks"
make functional-smoke

echo "[critical-path] validation completed"
