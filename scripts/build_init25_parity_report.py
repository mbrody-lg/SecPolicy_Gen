#!/usr/bin/env python3
"""Build an INIT-25 parity report from bounded execution summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_init25_parity_artifact import validate


def _load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _artifact_differences(authoritative: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, str]]:
    authoritative_artifacts = authoritative.get("artifacts")
    candidate_artifacts = candidate.get("artifacts")
    if not isinstance(authoritative_artifacts, dict):
        authoritative_artifacts = {}
    if not isinstance(candidate_artifacts, dict):
        candidate_artifacts = {}

    differences: list[dict[str, str]] = []
    for artifact in sorted(set(authoritative_artifacts) | set(candidate_artifacts)):
        authoritative_fields = set(_string_list(authoritative_artifacts.get(artifact)))
        candidate_fields = set(_string_list(candidate_artifacts.get(artifact)))
        for field in sorted(authoritative_fields - candidate_fields):
            differences.append({
                "artifact": artifact,
                "field": field,
                "reason": "candidate_missing_field",
            })
        for field in sorted(candidate_fields - authoritative_fields):
            differences.append({
                "artifact": artifact,
                "field": field,
                "reason": "candidate_extra_field",
            })
    return differences


def _evidence_coverage(authoritative: dict[str, Any], candidate: dict[str, Any]) -> dict[str, list[str]]:
    required = set(_string_list(authoritative.get("required_evidence_families")))
    covered = set(_string_list(candidate.get("covered_evidence_families")))
    return {
        "required_families": sorted(required),
        "covered_families": sorted(covered),
        "missing_families": sorted(required - covered),
    }


def _recommendation(
    *,
    contract_compatible: bool,
    runtime_errors: list[dict[str, Any]],
    missing_families: list[str],
) -> str:
    if runtime_errors:
        return "pause"
    if not contract_compatible or missing_families:
        return "narrow"
    return "continue"


def build_report(case_id: str, authoritative: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    artifact_differences = _artifact_differences(authoritative, candidate)
    evidence_coverage = _evidence_coverage(authoritative, candidate)
    runtime_errors = _object_list(candidate.get("runtime_errors"))
    authoritative_status = str(authoritative.get("validation_status") or "unknown")
    candidate_status = str(candidate.get("validation_status") or "unknown")
    contract_compatible = not artifact_differences and not runtime_errors
    report = {
        "case_id": case_id,
        "contract_compatible": contract_compatible,
        "artifact_differences": artifact_differences,
        "evidence_coverage": evidence_coverage,
        "validation_difference": {
            "authoritative_status": authoritative_status,
            "candidate_status": candidate_status,
            "changed": authoritative_status != candidate_status,
        },
        "runtime_errors": runtime_errors,
        "timing": {
            "authoritative_ms": authoritative.get("duration_ms"),
            "candidate_ms": candidate.get("duration_ms"),
        },
        "observability": {
            "correlation_id": candidate.get("correlation_id") or authoritative.get("correlation_id"),
            "has_runtime_invocation": bool(candidate.get("runtime_invocation")),
            "has_logs_ref": bool(candidate.get("logs_ref")),
        },
        "security_findings": _object_list(candidate.get("security_findings")),
        "recommendation": _recommendation(
            contract_compatible=contract_compatible,
            runtime_errors=runtime_errors,
            missing_families=evidence_coverage["missing_families"],
        ),
    }
    validate(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--authoritative", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.case_id,
        _load_object(args.authoritative),
        _load_object(args.candidate),
    )
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
