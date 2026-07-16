#!/usr/bin/env python3
"""Produce the fail-closed INIT-25 continue, narrow, or pause decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPORT_GATES = {
    "admission": "vertical_pilot_admission",
    "adjudication": "semantic_adjudication",
    "coordination": "coordination_ownership",
    "operational": "operational_readiness",
    "semantic": "paired_semantic_evidence",
}


def _digest(report: dict[str, Any]) -> str:
    encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _valid(report: dict[str, Any], gate: str) -> bool:
    return (
        report.get("schema_version") == "1.0"
        and report.get("initiative") == "INIT-25"
        and report.get("gate") == gate
    )


def decide(
    reports: dict[str, dict[str, Any]],
    expected_digests: dict[str, str],
) -> dict[str, Any]:
    integrity = all(
        isinstance(reports.get(name), dict)
        and expected_digests.get(name) == _digest(reports[name])
        and _valid(reports[name], gate)
        for name, gate in REPORT_GATES.items()
    )
    admission = reports.get("admission", {})
    semantic = reports.get("semantic", {})
    adjudication = reports.get("adjudication", {})
    operational = reports.get("operational", {})
    coordination = reports.get("coordination", {})
    semantic_digest = _digest(semantic) if isinstance(semantic, dict) else ""
    gates = {
        "report_integrity_verified": integrity,
        "pilot_admission_eligible": integrity and admission.get("eligible") is True,
        "paired_semantic_evidence_complete": (
            integrity
            and semantic.get("complete") is True
            and semantic.get("case_count") == 12
            and semantic.get("paired_case_count") == 12
        ),
        "independent_semantic_adjudication_passed": (
            integrity
            and adjudication.get("decision") == "passed"
            and adjudication.get("semantic_report_sha256") == semantic_digest
        ),
        "operational_readiness_passed": integrity and operational.get("ready") is True,
        "coordination_responsibility_removed": (
            integrity and coordination.get("responsibility_removed") is True
        ),
    }
    if all(gates.values()):
        direction = "continue"
    elif gates["pilot_admission_eligible"] and (
        gates["paired_semantic_evidence_complete"]
        or (integrity and operational.get("campaign_executed") is True)
    ):
        direction = "narrow"
    else:
        direction = "pause"
    return {
        "schema_version": "1.0",
        "initiative": "INIT-25",
        "gate": "direction_decision",
        "direction": direction,
        "initiative_open": True,
        "cutover_authorized": False,
        "gates": gates,
        "blockers": sorted(name for name, passed in gates.items() if not passed),
        "next_action": {
            "continue": "review_non_authoritative_vertical_pilot",
            "narrow": "reduce_scope_and_repeat_missing_gates",
            "pause": "resolve_INIT_11_and_runtime_boundary_blockers",
        }[direction],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in REPORT_GATES:
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--evidence-manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = {
        name: json.loads(getattr(args, name).read_text(encoding="utf-8"))
        for name in REPORT_GATES
    }
    manifest = json.loads(args.evidence_manifest.read_text(encoding="utf-8"))
    result = decide(reports, manifest.get("report_sha256", {}))
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
