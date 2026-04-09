#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASE_FILE="${1:-${ROOT_DIR}/migration/golden-contexts/case-01-healthcare-clinic.json}"
OUTPUT_DIR="${2:-${ROOT_DIR}/migration/phase1-shadow}"

mkdir -p "${OUTPUT_DIR}"

LEGACY_OUTPUT="${OUTPUT_DIR}/legacy-output.json"
CANDIDATE_OUTPUT="${OUTPUT_DIR}/candidate-output.json"
COMPARE_OUTPUT="${OUTPUT_DIR}/compare-output.json"

echo "[phase1-shadow] capturing legacy output"
"${ROOT_DIR}/scripts/run_legacy_phase1_case.sh" "${CASE_FILE}" "${LEGACY_OUTPUT}"

echo "[phase1-shadow] trying Docker Agent candidate output"
if "${ROOT_DIR}/scripts/run_cagent_phase1_case.sh" "${CASE_FILE}" > "${CANDIDATE_OUTPUT}"; then
  echo "[phase1-shadow] candidate output saved to ${CANDIDATE_OUTPUT}"
else
  echo "[phase1-shadow] candidate run failed; keeping legacy output only" >&2
  exit 1
fi

echo "[phase1-shadow] comparing outputs"
"${ROOT_DIR}/scripts/run_cagent_phase1_compare.sh" "${CANDIDATE_OUTPUT}" "${LEGACY_OUTPUT}" > "${COMPARE_OUTPUT}"
echo "[phase1-shadow] comparison saved to ${COMPARE_OUTPUT}"
