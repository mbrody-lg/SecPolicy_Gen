#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

fail() {
  printf "[bootstrap-test-env] %s\n" "$*" >&2
  exit 1
}

log() {
  printf "[bootstrap-test-env] %s\n" "$*"
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  fail "$PYTHON_BIN is required. Install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ or set PYTHON_BIN to a compatible interpreter."
fi

if ! "$PYTHON_BIN" - "$MIN_PYTHON_MAJOR" "$MIN_PYTHON_MINOR" <<'PY'
import sys

required = tuple(int(part) for part in sys.argv[1:3])
if sys.version_info[:2] < required:
    raise SystemExit(1)
PY
then
  version="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
  fail "$PYTHON_BIN is Python $version; Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required for local development."
fi

for requirements_file in \
  context-agent/requirements.txt \
  policy-agent/requirements.txt \
  validator-agent/requirements.txt
do
  if [[ ! -f "$requirements_file" ]]; then
    fail "Missing dependency file: $requirements_file"
  fi
done

if [[ ! -d "$VENV_DIR" ]]; then
  log "creating virtual environment in $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

log "upgrading pip"
"$VENV_DIR/bin/python" -m pip install --upgrade pip

log "installing context-agent dependencies"
"$VENV_DIR/bin/pip" install -r context-agent/requirements.txt

log "installing policy-agent dependencies"
"$VENV_DIR/bin/pip" install -r policy-agent/requirements.txt

log "installing validator-agent dependencies"
"$VENV_DIR/bin/pip" install -r validator-agent/requirements.txt

log "test environment bootstrap complete"
log "next: make host-fast-tests"
