from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.capture_init25_authoritative_summary import build_summary
from scripts.run_init25_contract_dry_run import ARTIFACT_FIELDS


CASE_ID = "healthcare-clinic-gdpr"
CONTEXT_ID = "context-123"
CORRELATION_ID = "smoke-context-123-correlation"


def _case_file() -> dict:
    return {
        "cases": [
            {
                "case_id": CASE_ID,
                "input": {"required_evidence_families": ["sector_norms", "legal_norms"]},
            }
        ]
    }


def _smoke_artifact() -> dict:
    context = {
        "context_id": CONTEXT_ID,
        "last_status": "accepted",
        "failure_reasons": [],
        "observability": {
            "pipeline_job": {
                "job_status": "completed",
                "job_stage": "completed",
                "job_correlation_id": CORRELATION_ID,
            },
            "requested_correlation_id": CORRELATION_ID,
            "generate_response_correlation_id": CORRELATION_ID,
            "header_correlation_id": CORRELATION_ID,
            "document_correlation_id": CORRELATION_ID,
            "pipeline_status": "completed",
            "has_policy_hop": True,
            "has_validator_hop": True,
        },
    }
    return {
        "schema_version": "1.0",
        "run": {
            "id": "smoke-runtime-1",
            "started_at": "2026-07-16T10:00:00+00:00",
            "finished_at": "2026-07-16T10:00:01.250000+00:00",
            "status": "passed",
            "mode": "runtime",
            "golden_dir": "/container/fixtures",
        },
        "contexts": [context],
        "summary": {"total_contexts": 1},
        "failures": [],
        "service_checks": {},
    }


def test_builds_bounded_authoritative_summary_from_runtime_smoke():
    summary = build_summary(_smoke_artifact(), _case_file(), CASE_ID, CONTEXT_ID)

    assert summary == {
        "schema_version": "1.0",
        "case_id": CASE_ID,
        "baseline_type": "live_authoritative_service_capture",
        "live_service_parity": False,
        "input_alignment": "unverified",
        "artifact_evidence": "contract_projection_not_observed",
        "validation_status": "accepted",
        "required_evidence_families": ["legal_norms", "sector_norms"],
        "correlation_id": CORRELATION_ID,
        "artifacts": {name: sorted(fields) for name, fields in sorted(ARTIFACT_FIELDS.items())},
        "duration_ms": 1250,
        "source": {
            "smoke_run_id": "smoke-runtime-1",
            "context_id": CONTEXT_ID,
            "mode": "runtime",
        },
        "runtime_errors": [
            {"error_code": "authoritative_input_unverified", "stage": "authoritative_capture"},
            {"error_code": "authoritative_artifacts_projected", "stage": "authoritative_capture"},
        ],
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["run"].update(mode="mock"), "mode must be runtime"),
        (lambda payload: payload["run"].update(status="failed"), "smoke run must be passed"),
        (lambda payload: payload["contexts"][0].pop("observability"), "observability must be an object"),
        (lambda payload: payload["contexts"][0]["observability"].update(has_policy_hop=False), "missing the policy hop"),
        (lambda payload: payload["contexts"][0]["observability"].update(has_validator_hop=False), "missing the validator hop"),
        (lambda payload: payload["contexts"][0].update(last_status="completed"), "last_status must be"),
        (
            lambda payload: payload["contexts"][0]["observability"].update(header_correlation_id="different"),
            "correlation ids are inconsistent",
        ),
    ],
)
def test_rejects_mock_failed_stale_or_incoherent_smoke(mutation, message):
    artifact = _smoke_artifact()
    mutation(artifact)
    if artifact["run"]["status"] == "failed":
        artifact["failures"] = [{"context_id": CONTEXT_ID, "reasons": ["failed"]}]

    with pytest.raises(SystemExit, match=message):
        build_summary(artifact, _case_file(), CASE_ID, CONTEXT_ID)


def test_rejects_absent_or_duplicate_context():
    absent = _smoke_artifact()
    absent["contexts"] = []
    absent["summary"]["total_contexts"] = 0
    with pytest.raises(SystemExit, match="must match exactly one context"):
        build_summary(absent, _case_file(), CASE_ID, CONTEXT_ID)

    duplicate = _smoke_artifact()
    duplicate["contexts"].append(copy.deepcopy(duplicate["contexts"][0]))
    duplicate["summary"]["total_contexts"] = 2
    with pytest.raises(SystemExit, match="must match exactly one context"):
        build_summary(duplicate, _case_file(), CASE_ID, CONTEXT_ID)


def test_rejects_sensitive_fields_and_does_not_copy_canary_text():
    sensitive = _smoke_artifact()
    sensitive["contexts"][0]["raw_output"] = "CANARY-DO-NOT-PERSIST"
    with pytest.raises(SystemExit, match="sensitive"):
        build_summary(sensitive, _case_file(), CASE_ID, CONTEXT_ID)

    artifact = _smoke_artifact()
    artifact["contexts"][0]["ignored_note"] = "CANARY-DO-NOT-PERSIST"
    serialized = json.dumps(build_summary(artifact, _case_file(), CASE_ID, CONTEXT_ID))
    assert "CANARY-DO-NOT-PERSIST" not in serialized
    assert "/container/fixtures" not in serialized


def test_cli_writes_deterministic_json(tmp_path):
    smoke_path = tmp_path / "smoke.json"
    case_path = tmp_path / "cases.json"
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "nested" / "second.json"
    smoke_path.write_text(json.dumps(_smoke_artifact()), encoding="utf-8")
    case_path.write_text(json.dumps(_case_file()), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "scripts" / "capture_init25_authoritative_summary.py"),
        "--smoke-artifact",
        str(smoke_path),
        "--case-file",
        str(case_path),
        "--case-id",
        CASE_ID,
        "--context-id",
        CONTEXT_ID,
        "--output",
    ]

    subprocess.run([*command, str(first_output)], check=True, cwd=tmp_path)
    subprocess.run([*command, str(second_output)], check=True, cwd=ROOT)

    assert first_output.read_bytes() == second_output.read_bytes()
    assert first_output.read_bytes().endswith(b"\n")
