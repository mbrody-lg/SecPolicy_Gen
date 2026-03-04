#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r context-agent/requirements.txt
"$VENV_DIR/bin/pip" install -r policy-agent/requirements.txt
"$VENV_DIR/bin/pip" install -r validator-agent/requirements.txt

echo "Test environment bootstrap complete."
echo "Use: .venv/bin/pytest -c pyproject.toml -m \"fast or route\""
