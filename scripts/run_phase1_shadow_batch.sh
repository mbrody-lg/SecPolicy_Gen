#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOLDEN_DIR="${1:-${ROOT_DIR}/migration/golden-contexts}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/migration/phase1-shadow-batch}"

if [[ ! -d "${GOLDEN_DIR}" ]]; then
  echo "Golden directory not found: ${GOLDEN_DIR}"
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}"

while IFS= read -r case_file; do
  case_name="$(basename "${case_file}" .json)"
  if [[ "${case_name}" == "schema" ]]; then
    continue
  fi

  case_output_dir="${OUTPUT_ROOT}/${case_name}"
  mkdir -p "${case_output_dir}"

  echo "[phase1-shadow-batch] processing ${case_name}"
  if "${ROOT_DIR}/scripts/run_phase1_shadow_case.sh" "${case_file}" "${case_output_dir}"; then
    echo "[phase1-shadow-batch] completed ${case_name}"
  else
    echo "[phase1-shadow-batch] failed ${case_name}" >&2
    printf '%s\n' '{"error":"shadow_case_failed"}' > "${case_output_dir}/compare-output.json"
  fi
done < <(find "${GOLDEN_DIR}" -maxdepth 1 -type f -name 'case-*.json' | sort)

"${ROOT_DIR}/scripts/summarize_phase1_shadow.py" --input-dir "${OUTPUT_ROOT}" > "${OUTPUT_ROOT}/summary.json"
python3 - "${OUTPUT_ROOT}/summary.json" "${OUTPUT_ROOT}/summary.md" <<'PY'
import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
Path(sys.argv[2]).write_text(summary.get("markdown_report", ""), encoding="utf-8")
PY
echo "[phase1-shadow-batch] summary saved to ${OUTPUT_ROOT}/summary.json"
echo "[phase1-shadow-batch] markdown summary saved to ${OUTPUT_ROOT}/summary.md"
