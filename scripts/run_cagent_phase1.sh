#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${ROOT_DIR}/agents/secpolicy_team.yaml"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Missing Docker Agent config: ${CONFIG_FILE}"
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker agent version >/dev/null 2>&1; then
  exec docker agent run "${CONFIG_FILE}" "$@"
fi

if command -v cagent >/dev/null 2>&1; then
  exec cagent run "${CONFIG_FILE}" "$@"
fi

if command -v docker-agent >/dev/null 2>&1; then
  exec docker-agent run "${CONFIG_FILE}" "$@"
fi

echo "Docker Agent is not installed or not available in PATH."
echo "Install Docker Desktop 4.63+ or a standalone docker-agent binary, then rerun:"
echo "  docker agent run ${CONFIG_FILE}"
exit 1
