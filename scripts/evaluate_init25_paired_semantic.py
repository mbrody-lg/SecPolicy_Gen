#!/usr/bin/env python3
"""Compare preregistered INIT-25 authoritative/candidate semantic evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "tests/fixtures/init25/semantic_pair_cases.json"
PROVENANCE_FIELDS = {
    "artifact_digest", "commit_sha", "config_digest", "invocation_id",
    "model_version", "run_id", "runtime_version", "timestamp",
}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_cases(path: Path = CASE_FILE) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or len(cases) != 12:
        raise ValueError("semantic_case_catalog_invalid")
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != 12 or len(set(ids)) != 12:
        raise ValueError("semantic_case_catalog_invalid")
    return cases


def _validate_arm(arm: dict[str, Any], *, basis: str, case_id: str, input_hash: str) -> None:
    if arm.get("case_id") != case_id or arm.get("input_hash") != input_hash:
        raise ValueError("paired_input_identity_mismatch")
    if arm.get("evidence_basis") != basis:
        raise ValueError("paired_evidence_not_observed")
    if any(not isinstance(arm.get(field), str) or not arm[field] for field in PROVENANCE_FIELDS):
        raise ValueError("paired_provenance_incomplete")
    for field in (
        "citation_ids", "evidence_families", "non_applicable_source_ids",
        "policy_invariants", "source_ids", "unsupported_high_impact_claims",
    ):
        if not isinstance(arm.get(field), list):
            raise ValueError("paired_semantic_signal_invalid")
    if arm.get("validation_status") not in {"accepted", "review", "rejected", "provider_error"}:
        raise ValueError("paired_semantic_signal_invalid")


def compare_pair(case: dict[str, Any], pair: dict[str, Any], index: int) -> dict[str, Any]:
    case_id = case["case_id"]
    input_hash = _canonical_hash(case["input"])
    authoritative = pair.get("authoritative")
    candidate = pair.get("candidate")
    if not isinstance(authoritative, dict) or not isinstance(candidate, dict):
        raise ValueError("paired_arm_missing")
    _validate_arm(authoritative, basis="observed", case_id=case_id, input_hash=input_hash)
    _validate_arm(candidate, basis="live", case_id=case_id, input_hash=input_hash)
    if authoritative["invocation_id"] == candidate["invocation_id"]:
        raise ValueError("paired_invocation_not_independent")

    required = set(case["required_evidence_families"])
    authoritative_evidence = set(authoritative["evidence_families"])
    candidate_evidence = set(candidate["evidence_families"])
    first, second = (("authoritative", "candidate") if index % 2 == 0 else ("candidate", "authoritative"))
    return {
        "case_id": case_id,
        "input_hash": input_hash,
        "blind_order": {"A": first, "B": second},
        "signals": {
            "validation_status_agreement": authoritative["validation_status"] == candidate["validation_status"],
            "authoritative_missing_evidence": sorted(required - authoritative_evidence),
            "candidate_missing_evidence": sorted(required - candidate_evidence),
            "candidate_non_applicable_sources": sorted(candidate["non_applicable_source_ids"]),
            "candidate_unsupported_high_impact_claims": len(candidate["unsupported_high_impact_claims"]),
            "citation_count_difference": len(candidate["citation_ids"]) - len(authoritative["citation_ids"]),
            "policy_invariant_difference": sorted(set(authoritative["policy_invariants"]) ^ set(candidate["policy_invariants"])),
            "source_overlap": sorted(set(authoritative["source_ids"]) & set(candidate["source_ids"])),
            "duration_ms": {
                "authoritative": authoritative.get("duration_ms"),
                "candidate": candidate.get("duration_ms"),
            },
        },
    }


def evaluate_batch(cases: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = {case["case_id"] for case in cases}
    pair_ids = [pair.get("case_id") for pair in pairs if isinstance(pair, dict)]
    duplicate_ids = sorted(case_id for case_id in set(pair_ids) if pair_ids.count(case_id) > 1)
    unknown_ids = sorted(case_id for case_id in pair_ids if case_id not in expected_ids)
    pairs_by_id = {pair["case_id"]: pair for pair in pairs if isinstance(pair, dict) and pair.get("case_id") in expected_ids}
    missing = sorted(case_id for case_id in expected_ids if case_id not in pairs_by_id)
    complete = not (missing or duplicate_ids or unknown_ids)
    comparisons = [] if not complete else [
        compare_pair(case, pairs_by_id[case["case_id"]], index)
        for index, case in enumerate(cases)
    ]
    return {
        "schema_version": "1.0",
        "initiative": "INIT-25",
        "gate": "paired_semantic_evidence",
        "case_count": len(cases),
        "paired_case_count": len(comparisons),
        "complete": complete,
        "missing_case_ids": missing,
        "duplicate_case_ids": duplicate_ids,
        "unknown_case_ids": unknown_ids,
        "comparisons": comparisons,
        "semantic_readiness": "not_assessed",
        "cutover_readiness": "not_ready",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))
    if not isinstance(pairs, list):
        raise SystemExit("INIT-25 semantic pairs must be a list")
    report = evaluate_batch(load_cases(), pairs)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    raise SystemExit(0 if report["complete"] else 2)


if __name__ == "__main__":
    main()
