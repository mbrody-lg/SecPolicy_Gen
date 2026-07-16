import hashlib

from scripts.assess_init25_operational_readiness import assess


def _evidence(root, name):
    path = root / f"{name}.json"
    path.write_text(f'{{"evidence":"{name}"}}', encoding="utf-8")
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "status": "passed"}


def _admission():
    return {"schema_version": "1.0", "initiative": "INIT-25", "gate": "vertical_pilot_admission", "eligible": True}


def _campaign(root):
    runs = []
    for index in range(30):
        runs.append({
            "run_id": f"run-{index}", "status": "success", "terminal": True,
            "error_classification": "none", "authoritative_mutations": 0,
            "orphan_processes": 0, "logs_verified": True, "cost_usd": 0.10,
            "authoritative_ms": 100, "candidate_ms": 110,
            "input_hash": f"{index:064x}", "result_hash": f"{index + 100:064x}",
            "provenance": {
                "commit_sha": "commit", "config_digest": "config", "model_version": "model",
                "runtime_version": "runtime", "timestamp": "2026-07-16T00:00:00Z",
            },
            "evidence": _evidence(root, f"run-{index}"),
        })
    drills = {name: _evidence(root, f"drill-{name}") for name in (
        "backup_restore", "corrupted_evidence", "provider_failure",
        "restart_recovery", "timeout_cancellation",
    )}
    drills["rollback"] = [_evidence(root, "rollback-1"), _evidence(root, "rollback-2")]
    controls = {name: _evidence(root, f"control-{name}") for name in (
        "auth_verified", "internal_only_network", "non_root",
        "otel_content_capture_disabled", "resources_explicit",
        "secrets_governed", "session_storage_governed",
    )}
    return {
        "budget_usd": 4, "runs": runs, "drills": drills,
        "runtime": {"controls": controls, "sbom": _evidence(root, "sbom"), "scan": _evidence(root, "scan")},
    }


def test_missing_or_malformed_campaign_fails_closed(tmp_path) -> None:
    assert assess({}, None, tmp_path)["ready"] is False
    assert assess(_admission(), {"runs": "thirty"}, tmp_path)["ready"] is False


def test_verified_campaign_can_reach_direction_review(tmp_path) -> None:
    report = assess(_admission(), _campaign(tmp_path), tmp_path)

    assert report["ready"] is True
    assert report["metrics"]["observed_runs"] == 30
    assert report["next_action"] == "review_direction"


def test_duplicate_runs_or_fabricated_supply_chain_digest_block(tmp_path) -> None:
    campaign = _campaign(tmp_path)
    campaign["runs"][1]["run_id"] = campaign["runs"][0]["run_id"]
    campaign["runtime"]["sbom"]["sha256"] = "0" * 64

    report = assess(_admission(), campaign, tmp_path)

    assert "at_least_30_unique_observed_runs" in report["blockers"]
    assert "supply_chain_evidence_verified" in report["blockers"]


def test_failed_runs_cannot_pass_success_threshold(tmp_path) -> None:
    campaign = _campaign(tmp_path)
    for run in campaign["runs"][:2]:
        run["status"] = "failed"
        run["error_classification"] = "provider_failure"

    assert assess(_admission(), campaign, tmp_path)["ready"] is False


def test_nearest_rank_p95_catches_two_latency_outliers(tmp_path) -> None:
    campaign = _campaign(tmp_path)
    for run in campaign["runs"][-2:]:
        run["candidate_ms"] = 200

    report = assess(_admission(), campaign, tmp_path)

    assert report["checks"]["latency_regression_bounded"] is False
