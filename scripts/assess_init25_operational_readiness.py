#!/usr/bin/env python3
"""Assess bounded INIT-25 operational campaign evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_DRILLS = {
    "backup_restore",
    "corrupted_evidence",
    "provider_failure",
    "restart_recovery",
    "timeout_cancellation",
}
REQUIRED_RUNTIME_CONTROLS = {
    "auth_verified",
    "internal_only_network",
    "non_root",
    "otel_content_capture_disabled",
    "resources_explicit",
    "secrets_governed",
    "session_storage_governed",
}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile)
    return ordered[index]


def assess(admission: dict[str, Any], campaign: dict[str, Any] | None) -> dict[str, Any]:
    runs = campaign.get("runs", []) if isinstance(campaign, dict) else []
    drills = campaign.get("drills", {}) if isinstance(campaign, dict) else {}
    runtime = campaign.get("runtime", {}) if isinstance(campaign, dict) else {}
    numeric_runs = [run for run in runs if isinstance(run, dict)]
    costs = [run.get("cost_usd") for run in numeric_runs]
    baseline_ms = [run.get("authoritative_ms") for run in numeric_runs]
    candidate_ms = [run.get("candidate_ms") for run in numeric_runs]
    metrics_valid = (
        len(numeric_runs) == len(runs)
        and all(isinstance(value, (int, float)) and value >= 0 for value in costs + baseline_ms + candidate_ms)
    )
    budget = campaign.get("budget_usd") if isinstance(campaign, dict) else None
    total_cost = sum(costs) if metrics_valid else None
    latency_regression = (
        _percentile(candidate_ms, 0.95) / max(_percentile(baseline_ms, 0.95), 1) - 1
        if metrics_valid and runs
        else None
    )
    quality_exception = campaign.get("quality_gain_preagreed") is True if isinstance(campaign, dict) else False

    checks = {
        "pilot_admission_eligible": admission.get("eligible") is True,
        "at_least_30_observed_runs": len(runs) >= 30,
        "budget_respected": (
            isinstance(budget, (int, float)) and budget > 0 and total_cost is not None and total_cost <= budget
        ),
        "latency_regression_bounded": (
            latency_regression is not None and (latency_regression <= 0.25 or quality_exception)
        ),
        "runs_terminal_and_classified": bool(runs) and all(
            run.get("terminal") is True and run.get("unclassified_errors") == 0 for run in numeric_runs
        ),
        "no_authoritative_mutations_or_orphans": bool(runs) and all(
            run.get("authoritative_mutations") == 0 and run.get("orphan_processes") == 0
            for run in numeric_runs
        ),
        "logs_verified": bool(runs) and all(run.get("logs_verified") is True for run in numeric_runs),
        "required_drills_passed": all(drills.get(name) == "passed" for name in REQUIRED_DRILLS),
        "rollback_rehearsed_twice": drills.get("rollback_runs", 0) >= 2,
        "runtime_controls_verified": all(runtime.get(name) is True for name in REQUIRED_RUNTIME_CONTROLS),
        "supply_chain_evidence_present": all(
            isinstance(runtime.get(name), str) and runtime[name] for name in ("sbom_digest", "scan_digest")
        ),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "1.0",
        "initiative": "INIT-25",
        "gate": "operational_readiness",
        "ready": not blockers,
        "campaign_executed": bool(runs),
        "checks": checks,
        "blockers": blockers,
        "metrics": {
            "observed_runs": len(runs),
            "total_cost_usd": total_cost,
            "candidate_latency_regression": latency_regression,
        },
        "next_action": "review_direction" if not blockers else "pause_runtime_expansion",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    admission = json.loads(args.admission.read_text(encoding="utf-8"))
    campaign = json.loads(args.campaign.read_text(encoding="utf-8")) if args.campaign else None
    result = assess(admission, campaign)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()
