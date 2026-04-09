#!/usr/bin/env python3
"""Compare a Docker Agent Phase 1 output against the legacy contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_KEYS = [
    "context_id",
    "language",
    "policy_text",
    "structured_plan",
    "generated_at",
    "policy_agent_version",
    "status",
    "reasons",
    "recommendations",
]

ALLOWED_STATUS = {"accepted", "review", "rejected"}
EXPECTED_TYPES = {
    "context_id": str,
    "language": str,
    "policy_text": str,
    "structured_plan": list,
    "generated_at": str,
    "policy_agent_version": str,
    "status": str,
    "reasons": list,
    "recommendations": list,
}


def _load_json(path: Path):
    raw = path.read_text(encoding="utf-8").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            raw = "\n".join(lines[1:-1]).strip()
    return json.loads(raw)


def _type_name(value):
    return type(value).__name__


def _collect_contract_issues(candidate: dict) -> dict:
    missing = [key for key in REQUIRED_KEYS if key not in candidate]
    type_mismatches = []
    for key, expected_type in EXPECTED_TYPES.items():
        if key in candidate and not isinstance(candidate[key], expected_type):
            type_mismatches.append(
                {
                    "field": key,
                    "expected": expected_type.__name__,
                    "actual": _type_name(candidate[key]),
                }
            )

    status_issue = None
    if "status" in candidate and isinstance(candidate["status"], str):
        if candidate["status"] not in ALLOWED_STATUS:
            status_issue = {
                "field": "status",
                "expected": sorted(ALLOWED_STATUS),
                "actual": candidate["status"],
            }

    return {
        "missing_keys": missing,
        "type_mismatches": type_mismatches,
        "status_issue": status_issue,
    }


def _compare_values(legacy: dict, candidate: dict) -> list:
    diffs = []
    shared_keys = sorted(set(legacy.keys()) & set(candidate.keys()))
    for key in shared_keys:
        if legacy[key] == candidate[key]:
            continue
        diffs.append(
            {
                "field": key,
                "legacy": legacy[key],
                "candidate": candidate[key],
            }
        )
    return diffs


def main():
    parser = argparse.ArgumentParser(
        description="Compare a Phase 1 Docker Agent output with the legacy policy/validator contract."
    )
    parser.add_argument("--candidate", required=True, help="Path to the candidate JSON output.")
    parser.add_argument(
        "--legacy",
        help="Optional path to a legacy JSON output. If omitted, only contract validation is performed.",
    )
    args = parser.parse_args()

    candidate_path = Path(args.candidate)
    candidate = _load_json(candidate_path)
    if not isinstance(candidate, dict):
        raise SystemExit("Candidate JSON must be an object.")

    contract_issues = _collect_contract_issues(candidate)
    result = {
        "candidate_file": str(candidate_path),
        "legacy_file": args.legacy,
        "contract_compatible": not any(
            [
                contract_issues["missing_keys"],
                contract_issues["type_mismatches"],
                contract_issues["status_issue"],
            ]
        ),
        "missing_keys": contract_issues["missing_keys"],
        "type_mismatches": contract_issues["type_mismatches"],
        "status_issue": contract_issues["status_issue"],
        "key_differences": [],
        "value_differences": [],
    }

    if args.legacy:
        legacy_path = Path(args.legacy)
        legacy = _load_json(legacy_path)
        if not isinstance(legacy, dict):
            raise SystemExit("Legacy JSON must be an object.")
        result["legacy_file"] = str(legacy_path)
        result["key_differences"] = {
            "only_in_legacy": sorted(set(legacy.keys()) - set(candidate.keys())),
            "only_in_candidate": sorted(set(candidate.keys()) - set(legacy.keys())),
        }
        result["value_differences"] = _compare_values(legacy, candidate)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
