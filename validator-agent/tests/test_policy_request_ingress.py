"""Canonical request sentinel must not disappear into legacy validation."""

import pytest

from app.services.logic import run_validation_pipeline


def test_validation_rejects_explicit_policy_request_before_execution():
    result = run_validation_pipeline({"policy_request": None})
    assert result["error_code"] == "policy_request_not_supported"
    assert result["status_code"] == 400


@pytest.mark.parametrize("marker,value", [
    ("contract", "secpolicy.policy_request"),
    ("approved_context", {}),
    ("policy_intent", {}),
    ("business_facts", {}),
    ("origin", {}),
])
def test_unwrapped_canonical_markers_never_fall_through_legacy_validation(marker, value):
    result = run_validation_pipeline({"context_id": "synthetic-context", marker: value})
    assert result["error_code"] == "policy_request_not_supported"
    assert result["status_code"] == 400
