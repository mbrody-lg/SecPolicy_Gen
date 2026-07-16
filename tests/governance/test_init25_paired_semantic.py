from collections import Counter

import pytest

from scripts.evaluate_init25_paired_semantic import _canonical_hash, compare_pair, evaluate_batch, load_cases


def _arm(case, basis, invocation):
    return {
        "case_id": case["case_id"],
        "input_hash": _canonical_hash(case["input"]),
        "evidence_basis": basis,
        "artifact_digest": "a" * 64,
        "commit_sha": "b" * 40,
        "config_digest": "c" * 64,
        "invocation_id": invocation,
        "model_version": "model-1",
        "run_id": f"run-{invocation}",
        "runtime_version": "runtime-1",
        "timestamp": "2026-07-16T00:00:00Z",
        "citation_ids": ["source-1"],
        "evidence_families": case["required_evidence_families"],
        "non_applicable_source_ids": [],
        "policy_invariants": ["least_privilege"],
        "source_ids": ["source-1"],
        "unsupported_high_impact_claims": [],
        "validation_status": "accepted",
        "duration_ms": 100,
    }


def _pair(case):
    return {
        "case_id": case["case_id"],
        "authoritative": _arm(case, "observed", f"auth-{case['case_id']}"),
        "candidate": _arm(case, "live", f"candidate-{case['case_id']}"),
    }


def test_semantic_catalog_is_preregistered_and_covers_required_matrix():
    cases = load_cases()

    assert len(cases) == 12
    assert Counter(case["language"] for case in cases) == {"ca": 4, "en": 4, "es": 4}
    assert {case["sector"] for case in cases} == {"healthcare", "iot", "legal"}
    assert {case["scenario"] for case in cases} >= {
        "incomplete_context", "non_applicable_sources", "provider_failure", "unsupported_claims"
    }
    assert all(not ({"expected", "policy", "score", "recommendation"} & set(case)) for case in cases)


@pytest.mark.parametrize("mutation,error", [
    (lambda pair: pair["candidate"].update(evidence_basis="simulated"), "paired_evidence_not_observed"),
    (lambda pair: pair["candidate"].update(input_hash="0" * 64), "paired_input_identity_mismatch"),
    (lambda pair: pair["candidate"].update(invocation_id=pair["authoritative"]["invocation_id"]), "paired_invocation_not_independent"),
])
def test_pair_rejects_circular_or_unobserved_evidence(mutation, error):
    case = load_cases()[0]
    pair = _pair(case)
    mutation(pair)

    with pytest.raises(ValueError, match=error):
        compare_pair(case, pair, 0)


def test_batch_reports_descriptive_signals_without_readiness_claims():
    cases = load_cases()
    report = evaluate_batch(cases, [_pair(case) for case in cases])

    assert report["initiative"] == "INIT-25"
    assert report["gate"] == "paired_semantic_evidence"
    assert report["complete"] is True
    assert report["paired_case_count"] == 12
    assert report["semantic_readiness"] == "not_assessed"
    assert report["cutover_readiness"] == "not_ready"
    assert set(report["comparisons"][0]) == {"case_id", "input_hash", "blind_order", "signals"}
    assert report["comparisons"][0]["blind_order"] != report["comparisons"][1]["blind_order"]


def test_batch_is_incomplete_when_live_pairs_are_missing():
    cases = load_cases()
    report = evaluate_batch(cases, [])

    assert report["complete"] is False
    assert report["paired_case_count"] == 0
    assert len(report["missing_case_ids"]) == 12
