#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STACK_STARTED=0

cleanup() {
  if [[ "$STACK_STARTED" -eq 1 ]]; then
    make down >/dev/null
  fi
}

trap cleanup EXIT

echo "[critical-path] starting docker stack"
make up
STACK_STARTED=1

echo "[critical-path] running service suites"
make context-tests
make policy-tests
make validator-tests

echo "[critical-path] resetting stack before smoke validation"
make down >/dev/null
STACK_STARTED=0

echo "[critical-path] running end-to-end functional smoke"
make functional-smoke

echo "[critical-path] validation completed"
