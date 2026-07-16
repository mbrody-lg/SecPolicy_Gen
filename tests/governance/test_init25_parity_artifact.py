import sys
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_init25_parity_artifact import validate  # noqa: E402


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "init25" / "parity_reports"


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
        "assessment": {
            "contract_recommendation": "continue",
            "semantic_readiness": "not_assessed",
            "cutover_readiness": "not_ready",
            "evidence_basis": {
                "authoritative": "projected",
                "candidate": "simulated",
            },
        },
    }


def test_init25_parity_artifact_accepts_minimal_valid_report():
    validate(_valid_report())


def test_init25_parity_artifact_accepts_legacy_contract_report():
    report = _valid_report()
    report.pop("assessment")

    validate(report)


def test_init25_parity_artifact_rejects_mismatched_assessment_recommendation():
    report = _valid_report()
    report["assessment"]["contract_recommendation"] = "narrow"

    with pytest.raises(SystemExit, match="must match recommendation"):
        validate(report)


@pytest.mark.parametrize(
    ("authoritative", "candidate"),
    [("projected", "live"), ("observed", "simulated"), ("unverified", "live")],
)
def test_init25_parity_artifact_rejects_cutover_ready_without_live_observed_evidence(
    authoritative, candidate
):
    report = _valid_report()
    report["assessment"].update({
        "cutover_readiness": "ready",
        "evidence_basis": {"authoritative": authoritative, "candidate": candidate},
    })

    with pytest.raises(SystemExit, match="cutover_readiness is invalid"):
        validate(report)


def test_init25_parity_artifact_rejects_ready_without_semantic_evidence_contract():
    report = _valid_report()
    report["assessment"].update({
        "semantic_readiness": "ready",
        "cutover_readiness": "ready",
        "evidence_basis": {"authoritative": "observed", "candidate": "live"},
    })

    with pytest.raises(SystemExit, match="semantic_readiness is invalid"):
        validate(report)


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

    with pytest.raises(SystemExit, match="contract_compatible is inconsistent"):
        validate(report)


def test_init25_parity_artifact_rejects_continue_with_validation_drift():
    report = _valid_report()
    report["validation_difference"]["candidate_status"] = "review"
    report["validation_difference"]["changed"] = True

    with pytest.raises(SystemExit, match="continue requires unchanged validation status"):
        validate(report)


def test_init25_parity_artifact_rejects_continue_with_security_findings():
    report = _valid_report()
    report["security_findings"] = [{"finding_code": "unsafe_permission"}]

    with pytest.raises(SystemExit, match="continue requires no security findings"):
        validate(report)


def test_init25_parity_artifact_rejects_continue_with_missing_coverage_shape():
    report = _valid_report()
    report["evidence_coverage"] = {}

    with pytest.raises(SystemExit, match="required_families must be a list of strings"):
        validate(report)


def test_init25_parity_artifact_rejects_continue_with_missing_validation_shape():
    report = _valid_report()
    report["validation_difference"] = {}

    with pytest.raises(SystemExit, match="authoritative_status must be a string"):
        validate(report)


def test_init25_parity_artifact_rejects_inconsistent_derived_coverage():
    report = _valid_report()
    report["evidence_coverage"]["covered_families"] = ["legal_norms"]

    with pytest.raises(SystemExit, match="missing_families is inconsistent"):
        validate(report)


def test_init25_parity_artifact_rejects_narrow_when_runtime_error_requires_pause():
    report = _valid_report()
    report["contract_compatible"] = False
    report["runtime_errors"] = [{"error_code": "candidate_failed"}]
    report["recommendation"] = "narrow"
    report["assessment"]["contract_recommendation"] = "narrow"

    with pytest.raises(SystemExit, match="recommendation must be pause"):
        validate(report)


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_DIR.glob("*.json")))
def test_init25_parity_fixture_contracts_are_valid(fixture_path):
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    validate(payload)
