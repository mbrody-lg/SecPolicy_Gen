#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEAM_CONFIG="${ROOT_DIR}/agents/secpolicy_team.yaml"
DEFAULT_CASE="${ROOT_DIR}/migration/golden-contexts/case-01-healthcare-clinic.json"

CASE_FILE="${1:-$DEFAULT_CASE}"
shift || true

if [[ ! -f "${TEAM_CONFIG}" ]]; then
  echo "Missing Docker Agent config: ${TEAM_CONFIG}"
  exit 1
fi

if [[ ! -f "${CASE_FILE}" ]]; then
  echo "Golden case file not found: ${CASE_FILE}"
  exit 1
fi

PROMPT_FILE="$(mktemp)"
cleanup() {
  rm -f "${PROMPT_FILE}"
}
trap cleanup EXIT

python3 - "${CASE_FILE}" "${ROOT_DIR}" > "${PROMPT_FILE}" <<'PY'
import json
import sys
from pathlib import Path

root_dir = Path(sys.argv[2]).resolve()
case_path = Path(sys.argv[1]).resolve()
case_data = json.loads(case_path.read_text(encoding="utf-8"))
strategy_id = case_data.get("strategy_id")
if not strategy_id:
    raise SystemExit("Missing strategy_id in case file.")

strategy_path = root_dir / "migration" / "strategies" / f"{strategy_id}.yaml"
if not strategy_path.exists():
    raise SystemExit(f"Strategy file not found: {strategy_path}")

context = case_data.get("context", {})
context_lines = "\n".join(f"- {key}: {value}" for key, value in context.items())

print(
    f"""Run a Phase 1 migration dry run for the following SecPolicy_Gen golden case.

Case metadata:
- case_id: {case_data.get("case_id", "unknown")}
- scenario: {case_data.get("scenario", "unknown")}
- strategy_id: {strategy_id}
- strategy_file: {strategy_path.relative_to(root_dir)}
- source_case_file: {case_path.relative_to(root_dir)}

Business context:
{context_lines}

Execution instructions:
- Read the repository code and the strategy file before answering.
- Use the current three-service pipeline as the baseline behavior.
- Simulate the cagent Phase 1 flow: context normalization, policy drafting, validator decision.
- Be conservative when information is incomplete.

Return only one JSON object with this shape:
{{
  "context_id": "{case_data.get("case_id", "phase1-case")}",
  "language": "en",
  "policy_text": "string",
  "structured_plan": [],
  "generated_at": "ISO-8601 string",
  "policy_agent_version": "phase1-cagent",
  "status": "accepted|review|rejected",
  "reasons": ["string"],
  "recommendations": ["string"],
  "parity_notes": "short explanation"
}}

Hard rules:
- `reasons` must be a JSON array.
- `recommendations` must be a JSON array.
- `status` must be one of `accepted`, `review`, or `rejected`.
- Do not wrap the JSON in markdown fences.
"""
)
PY

if command -v docker >/dev/null 2>&1 && docker agent version >/dev/null 2>&1; then
  exec docker agent run "${TEAM_CONFIG}" \
    --agent root \
    --working-dir "${ROOT_DIR}" \
    --prompt-file "${PROMPT_FILE}" \
    --exec \
    "$@"
fi

if command -v cagent >/dev/null 2>&1; then
  exec cagent run "${TEAM_CONFIG}" \
    --agent root \
    --working-dir "${ROOT_DIR}" \
    --prompt-file "${PROMPT_FILE}" \
    --exec \
    "$@"
fi

if command -v docker-agent >/dev/null 2>&1; then
  exec docker-agent run "${TEAM_CONFIG}" \
    --agent root \
    --working-dir "${ROOT_DIR}" \
    --prompt-file "${PROMPT_FILE}" \
    --exec \
    "$@"
fi

echo "Docker Agent is not installed or not available in PATH."
exit 1
