#!/usr/bin/env python3
"""Assess bounded INIT-25 operational campaign evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


REQUIRED_DRILLS = {
    "backup_restore", "corrupted_evidence", "provider_failure",
    "restart_recovery", "timeout_cancellation",
}
REQUIRED_RUNTIME_CONTROLS = {
    "auth_verified", "internal_only_network", "non_root",
    "otel_content_capture_disabled", "resources_explicit",
    "secrets_governed", "session_storage_governed",
}
REQUIRED_PROVENANCE = {
    "commit_sha", "config_digest", "model_version", "runtime_version", "timestamp",
}
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _verified(root: Path | None, entry: Any) -> bool:
    if root is None or not isinstance(entry, dict) or entry.get("status") != "passed":
        return False
    expected = entry.get("sha256")
    if not isinstance(expected, str) or not HEX_DIGEST.fullmatch(expected):
        return False
    try:
        artifact = (root / entry["path"]).resolve(strict=True)
        artifact.relative_to(root.resolve())
        return hashlib.sha256(artifact.read_bytes()).hexdigest() == expected
    except (KeyError, OSError, TypeError, ValueError):
        return False


def assess(
    admission: dict[str, Any],
    campaign: dict[str, Any] | None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    valid_campaign = isinstance(campaign, dict)
    runs = campaign.get("runs", []) if valid_campaign else []
    drills = campaign.get("drills", {}) if valid_campaign else {}
    runtime = campaign.get("runtime", {}) if valid_campaign else {}
    runs = runs if isinstance(runs, list) else []
    drills = drills if isinstance(drills, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    controls = runtime.get("controls", {})
    controls = controls if isinstance(controls, dict) else {}
    numeric_fields = ("cost_usd", "authoritative_ms", "candidate_ms")
    valid_runs = [run for run in runs if isinstance(run, dict)]
    run_ids = [run.get("run_id") for run in valid_runs]
    run_shape_valid = len(valid_runs) == len(runs) and all(
        isinstance(run.get("run_id"), str)
        and run["run_id"]
        and run.get("status") in {"success", "failed"}
        and run.get("terminal") is True
        and isinstance(run.get("error_classification"), str)
        and run["error_classification"]
        and all(isinstance(run.get(field), (int, float)) and not isinstance(run.get(field), bool) and run[field] >= 0 for field in numeric_fields)
        and all(isinstance(run.get(field), str) and HEX_DIGEST.fullmatch(run[field]) for field in ("input_hash", "result_hash"))
        and isinstance(run.get("provenance"), dict)
        and all(isinstance(run["provenance"].get(field), str) and run["provenance"][field] for field in REQUIRED_PROVENANCE)
        and _verified(artifact_root, run.get("evidence"))
        for run in valid_runs
    )
    unique_runs = run_shape_valid and len(run_ids) == len(set(run_ids))
    costs = [run["cost_usd"] for run in valid_runs] if run_shape_valid else []
    baseline_ms = [run["authoritative_ms"] for run in valid_runs] if run_shape_valid else []
    candidate_ms = [run["candidate_ms"] for run in valid_runs] if run_shape_valid else []
    successes = sum(run.get("status") == "success" for run in valid_runs)
    success_rate = successes / len(valid_runs) if valid_runs else 0.0
    budget = campaign.get("budget_usd") if valid_campaign else None
    total_cost = sum(costs) if costs else None
    latency_regression = (
        _percentile(candidate_ms, 0.95) / max(_percentile(baseline_ms, 0.95), 1) - 1
        if candidate_ms else None
    )
    quality_exception = campaign.get("quality_gain_preagreed") is True if valid_campaign else False
    rollback = drills.get("rollback", [])
    rollback = rollback if isinstance(rollback, list) else []
    admission_valid = (
        isinstance(admission, dict)
        and admission.get("schema_version") == "1.0"
        and admission.get("initiative") == "INIT-25"
        and admission.get("gate") == "vertical_pilot_admission"
        and admission.get("eligible") is True
    )

    checks = {
        "pilot_admission_eligible": admission_valid,
        "at_least_30_unique_observed_runs": len(valid_runs) >= 30 and unique_runs,
        "run_evidence_verified": run_shape_valid and bool(valid_runs),
        "success_rate_at_least_95_percent": success_rate >= 0.95,
        "budget_respected": isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0 and total_cost is not None and total_cost <= budget,
        "latency_regression_bounded": latency_regression is not None and (latency_regression <= 0.25 or quality_exception),
        "errors_classified": bool(valid_runs) and all(
            run["error_classification"] == "none" if run["status"] == "success"
            else run["error_classification"] != "none"
            for run in valid_runs
        ),
        "no_authoritative_mutations_or_orphans": bool(valid_runs) and all(
            run.get("authoritative_mutations") == 0 and run.get("orphan_processes") == 0
            for run in valid_runs
        ),
        "logs_verified": bool(valid_runs) and all(run.get("logs_verified") is True for run in valid_runs),
        "required_drills_verified": all(_verified(artifact_root, drills.get(name)) for name in REQUIRED_DRILLS),
        "rollback_rehearsed_twice": len(rollback) >= 2 and all(_verified(artifact_root, item) for item in rollback),
        "runtime_controls_verified": all(_verified(artifact_root, controls.get(name)) for name in REQUIRED_RUNTIME_CONTROLS),
        "supply_chain_evidence_verified": all(_verified(artifact_root, runtime.get(name)) for name in ("sbom", "scan")),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "1.0", "initiative": "INIT-25",
        "gate": "operational_readiness", "ready": not blockers,
        "campaign_executed": bool(runs), "checks": checks, "blockers": blockers,
        "metrics": {
            "observed_runs": len(valid_runs), "success_rate": success_rate,
            "total_cost_usd": total_cost, "candidate_latency_regression": latency_regression,
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
    result = assess(admission, campaign, args.campaign.parent if args.campaign else None)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()
