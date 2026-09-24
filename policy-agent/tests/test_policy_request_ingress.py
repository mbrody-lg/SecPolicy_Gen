"""Canonical request sentinel must not disappear into legacy generation."""

import pytest

from app.services.logic import run_generation_pipeline, run_policy_update_pipeline, validate_generation_payload


def test_generation_rejects_explicit_policy_request_before_execution():
    payload = {
        "context_id": "synthetic-context", "refined_prompt": "Synthetic prompt",
        "language": "en", "model_version": "mock", "policy_request": None,
    }
    result = run_generation_pipeline(payload)
    assert result["error_code"] == "policy_request_not_supported"
    assert result["status_code"] == 400


def test_update_rejects_explicit_policy_request_before_persistence():
    result = run_policy_update_pipeline({"policy_request": {}}, "synthetic-context")
    assert result["error_code"] == "policy_request_not_supported"
    assert result["status_code"] == 400


@pytest.mark.parametrize("marker,value", [
    ("contract", "secpolicy.policy_request"),
    ("approved_context", {}),
    ("policy_intent", {}),
    ("business_facts", {}),
    ("origin", {}),
])
def test_unwrapped_canonical_markers_never_fall_through_legacy_generation(marker, value):
    payload = {
        "context_id": "synthetic-context", "refined_prompt": "Synthetic prompt",
        "language": "en", "model_version": "mock", marker: value,
    }
    result = run_generation_pipeline(payload)
    assert result["error_code"] == "policy_request_not_supported"
    assert result["status_code"] == 400


def test_legacy_generation_still_validates():
    payload = {
        "context_id": "synthetic-context", "refined_prompt": "Synthetic prompt",
        "language": "en", "model_version": "mock",
    }
    assert validate_generation_payload(payload)["context_id"] == "synthetic-context"
