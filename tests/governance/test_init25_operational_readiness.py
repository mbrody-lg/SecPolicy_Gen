from scripts.assess_init25_operational_readiness import assess


def _campaign() -> dict:
    run = {
        "terminal": True,
        "unclassified_errors": 0,
        "authoritative_mutations": 0,
        "orphan_processes": 0,
        "logs_verified": True,
        "cost_usd": 0.10,
        "authoritative_ms": 100,
        "candidate_ms": 110,
    }
    return {
        "budget_usd": 4,
        "runs": [dict(run) for _ in range(30)],
        "drills": {
            "backup_restore": "passed",
            "corrupted_evidence": "passed",
            "provider_failure": "passed",
            "restart_recovery": "passed",
            "timeout_cancellation": "passed",
            "rollback_runs": 2,
        },
        "runtime": {
            "auth_verified": True,
            "internal_only_network": True,
            "non_root": True,
            "otel_content_capture_disabled": True,
            "resources_explicit": True,
            "secrets_governed": True,
            "session_storage_governed": True,
            "sbom_digest": "sha256:sbom",
            "scan_digest": "sha256:scan",
        },
    }


def test_missing_campaign_fails_closed() -> None:
    report = assess({"eligible": False}, None)

    assert report["ready"] is False
    assert report["campaign_executed"] is False
    assert report["next_action"] == "pause_runtime_expansion"


def test_complete_observed_campaign_can_reach_direction_review() -> None:
    report = assess({"eligible": True}, _campaign())

    assert report["ready"] is True
    assert report["metrics"]["observed_runs"] == 30
    assert report["next_action"] == "review_direction"


def test_mutation_or_missing_drill_blocks_readiness() -> None:
    campaign = _campaign()
    campaign["runs"][0]["authoritative_mutations"] = 1
    campaign["drills"]["provider_failure"] = "failed"

    report = assess({"eligible": True}, campaign)

    assert report["ready"] is False
    assert "no_authoritative_mutations_or_orphans" in report["blockers"]
    assert "required_drills_passed" in report["blockers"]


def test_latency_regression_requires_preagreed_quality_exception() -> None:
    campaign = _campaign()
    for run in campaign["runs"]:
        run["candidate_ms"] = 150

    assert assess({"eligible": True}, campaign)["ready"] is False
    campaign["quality_gain_preagreed"] = True
    assert assess({"eligible": True}, campaign)["ready"] is True
