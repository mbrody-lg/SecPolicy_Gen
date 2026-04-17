#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_PYTEST="$ROOT_DIR/.venv/bin/pytest"
MARK_EXPR='fast or route'

if [[ ! -x "$VENV_PYTEST" ]]; then
  echo "Missing $VENV_PYTEST. Run: make bootstrap-test-env" >&2
  exit 1
fi

run_service_tests() {
  local service_dir="$1"
  shift
  echo "==> ${service_dir}"
  PYTHONPATH="$ROOT_DIR/$service_dir" \
    "$VENV_PYTEST" -c "$ROOT_DIR/pyproject.toml" -m "$MARK_EXPR" "$@"
}

run_service_tests \
  "context-agent" \
  "$ROOT_DIR/context-agent/tests/test_routes.py" \
  "$ROOT_DIR/context-agent/tests/test_services_logic.py"

run_service_tests \
  "policy-agent" \
  "$ROOT_DIR/policy-agent/tests/test_openai_routes.py" \
  "$ROOT_DIR/policy-agent/tests/test_update_policy_route.py"

run_service_tests \
  "validator-agent" \
  "$ROOT_DIR/validator-agent/tests/test_routes.py"
