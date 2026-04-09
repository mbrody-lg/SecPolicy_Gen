#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 CANDIDATE_JSON [LEGACY_JSON]"
  exit 1
fi

CANDIDATE_FILE="$1"
LEGACY_FILE="${2:-}"

if [[ -n "${LEGACY_FILE}" ]]; then
  exec python3 "${ROOT_DIR}/scripts/compare_phase1_output.py" \
    --candidate "${CANDIDATE_FILE}" \
    --legacy "${LEGACY_FILE}"
fi

exec python3 "${ROOT_DIR}/scripts/compare_phase1_output.py" \
  --candidate "${CANDIDATE_FILE}"
