import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_init25_parity_artifact import validate  # noqa: E402


def _valid_report():
    return {
        "case_id": "healthcare-clinic-gdpr",
        "contract_compatible": True,
        "artifact_differences": [],
        "evidence_coverage": {
            "required_families": ["legal_norms", "sector_norms"],
            "covered_families": ["legal_norms", "sector_norms"],
            "missing_families": [],
        },
        "validation_difference": {
            "authoritative_status": "accepted",
            "candidate_status": "accepted",
            "changed": False,
        },
        "runtime_errors": [],
        "timing": {
            "authoritative_ms": 1200,
            "candidate_ms": 1300,
        },
        "observability": {
            "correlation_id": "init25-parity-healthcare-clinic",
            "has_runtime_invocation": True,
            "has_logs_ref": True,
        },
        "security_findings": [],
        "recommendation": "continue",
    }


def test_init25_parity_artifact_accepts_minimal_valid_report():
    validate(_valid_report())


def test_init25_parity_artifact_rejects_missing_required_fields():
    report = _valid_report()
    del report["recommendation"]

    with pytest.raises(SystemExit, match="missing required fields: recommendation"):
        validate(report)


def test_init25_parity_artifact_rejects_invalid_recommendation():
    report = _valid_report()
    report["recommendation"] = "merge"

    with pytest.raises(SystemExit, match="recommendation must be continue, narrow, or pause"):
        validate(report)


def test_init25_parity_artifact_rejects_raw_or_sensitive_payload_keys():
    report = _valid_report()
    report["observability"]["raw_output"] = {"token": "secret"}

    with pytest.raises(SystemExit, match="sensitive or raw runtime payload keys"):
        validate(report)


def test_init25_parity_artifact_rejects_contract_success_with_runtime_errors():
    report = _valid_report()
    report["runtime_errors"] = [{"error_code": "candidate_failed"}]

    with pytest.raises(SystemExit, match="contract-compatible reports must not contain runtime_errors"):
        validate(report)
