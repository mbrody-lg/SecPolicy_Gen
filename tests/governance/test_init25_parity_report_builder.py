import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_init25_parity_report import build_report  # noqa: E402
from scripts.validate_init25_parity_artifact import validate  # noqa: E402


def _authoritative_summary():
    return {
        "validation_status": "accepted",
        "required_evidence_families": ["legal_norms", "sector_norms"],
        "duration_ms": 1200,
        "correlation_id": "auth-correlation",
        "artifacts": {
            "context_agent.policy_handoff.v1": [
                "version",
                "context_ready_for_policy",
                "retrieval_hints",
            ],
            "rag.retrieval_evidence": ["text", "source_id", "collection"],
        },
    }


def _candidate_summary():
    return {
        "validation_status": "accepted",
        "covered_evidence_families": ["legal_norms", "sector_norms"],
        "duration_ms": 1300,
        "correlation_id": "candidate-correlation",
        "runtime_invocation": {"mode": "dry_run"},
        "logs_ref": "artifacts/init25/case/logs.jsonl",
        "artifacts": {
            "context_agent.policy_handoff.v1": [
                "version",
                "context_ready_for_policy",
                "retrieval_hints",
            ],
            "rag.retrieval_evidence": ["text", "source_id", "collection"],
        },
    }


def test_init25_parity_report_builder_recommends_continue_for_matching_contracts():
    report = build_report("healthcare-clinic-gdpr", _authoritative_summary(), _candidate_summary())

    validate(report)
    assert report["contract_compatible"] is True
    assert report["recommendation"] == "continue"
    assert report["validation_difference"]["changed"] is False


def test_init25_parity_report_builder_recommends_narrow_for_missing_evidence():
    candidate = _candidate_summary()
    candidate["covered_evidence_families"] = ["legal_norms"]

    report = build_report("iot-startup-device-security", _authoritative_summary(), candidate)

    assert report["contract_compatible"] is True
    assert report["evidence_coverage"]["missing_families"] == ["sector_norms"]
    assert report["recommendation"] == "narrow"


def test_init25_parity_report_builder_recommends_pause_for_runtime_errors():
    candidate = _candidate_summary()
    candidate["runtime_errors"] = [{"error_code": "candidate_failed", "stage": "dry_run"}]

    report = build_report("legal-office-confidentiality", _authoritative_summary(), candidate)

    assert report["contract_compatible"] is False
    assert report["recommendation"] == "pause"


def test_init25_parity_report_builder_narrows_on_validation_drift():
    candidate = _candidate_summary()
    candidate["validation_status"] = "review"

    report = build_report("healthcare-clinic-gdpr", _authoritative_summary(), candidate)

    assert report["contract_compatible"] is True
    assert report["validation_difference"]["changed"] is True
    assert report["recommendation"] == "narrow"


def test_init25_parity_report_builder_pauses_on_security_findings():
    candidate = _candidate_summary()
    candidate["security_findings"] = [{"finding_code": "unsafe_permission", "stage": "dry_run"}]

    report = build_report("healthcare-clinic-gdpr", _authoritative_summary(), candidate)

    assert report["contract_compatible"] is True
    assert report["recommendation"] == "pause"


def test_init25_parity_report_builder_cli_writes_valid_report(tmp_path):
    authoritative = tmp_path / "authoritative.json"
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "report.json"
    authoritative.write_text(json.dumps(_authoritative_summary()), encoding="utf-8")
    candidate.write_text(json.dumps(_candidate_summary()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_init25_parity_report.py",
            "--case-id",
            "healthcare-clinic-gdpr",
            "--authoritative",
            str(authoritative),
            "--candidate",
            str(candidate),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    validate(report)
    assert report["recommendation"] == "continue"
