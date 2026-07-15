from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_init25_contract_dry_run import run_case  # noqa: E402


CASE_FILE = ROOT / "tests" / "fixtures" / "init25" / "dry_run_cases.json"


def _cases():
    return json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["case_id"])
def test_init25_contract_cases_emit_expected_decisions(case):
    artifacts, summary, report = run_case(case)

    if case["input"]["context_ready_for_policy"]:
        assert set(artifacts) == {
            "context_agent.policy_handoff.v1",
            "rag.retrieval_context",
            "rag.retrieval_plan",
            "rag.retrieval_evidence",
            "policy_agent.policy_draft",
            "validator.validation_payload",
            "validator.validation_decision",
        }
        assert summary["validation_status"] == artifacts["validator.validation_decision"]["status"]
    else:
        assert set(artifacts) == {"context_agent.policy_handoff.v1"}
    assert report["recommendation"] == case["expected_recommendation"]


def test_init25_contract_runner_rejects_sensitive_candidate_fields():
    case = deepcopy(_cases()[0])
    case["input"]["provider_payload"] = {"model": "example"}

    with pytest.raises(SystemExit, match="sensitive or raw runtime payload keys"):
        run_case(case)


def test_init25_contract_runner_derives_evidence_coverage_from_artifacts():
    case = deepcopy(_cases()[0])
    case["input"]["evidence"] = [case["input"]["evidence"][0]]

    _, summary, report = run_case(case)

    assert summary["covered_evidence_families"] == ["legal_norms"]
    assert report["recommendation"] == "narrow"


def test_init25_contract_runner_rejects_malformed_retrieval_values():
    case = deepcopy(_cases()[0])
    case["input"]["evidence"][0]["family"] = None

    _, _, report = run_case(case)

    assert report["recommendation"] == "pause"
    assert any(error["error_code"] == "retrieval_step_invalid" for error in report["runtime_errors"])


def test_init25_contract_runner_rejects_empty_policy_content():
    case = deepcopy(_cases()[0])
    case["input"]["policy_text"] = ""

    _, _, report = run_case(case)

    assert report["recommendation"] == "pause"
    assert any(
        error["stage"] == "policy_agent.policy_draft" and error.get("field") == "policy_text"
        for error in report["runtime_errors"]
    )


def test_init25_contract_runner_writes_deterministic_evidence(tmp_path):
    case = _cases()[0]
    outputs = []

    for run_number in (1, 2):
        output_dir = tmp_path / f"run-{run_number}"
        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_init25_contract_dry_run.py",
                "--case-file",
                str(CASE_FILE),
                "--case-id",
                case["case_id"],
                "--output-dir",
                str(output_dir),
            ],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        outputs.append({path.name: path.read_text(encoding="utf-8") for path in output_dir.iterdir()})

    assert outputs[0] == outputs[1]
    assert set(outputs[0]) == {
        "candidate-artifacts.json",
        "candidate-summary.json",
        "parity-report.json",
    }


def test_init25_contract_runner_preserves_pause_evidence_and_exits_nonzero(tmp_path):
    case = _cases()[2]
    output_dir = tmp_path / "pause"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_init25_contract_dry_run.py",
            "--case-file",
            str(CASE_FILE),
            "--case-id",
            case["case_id"],
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    report = json.loads((output_dir / "parity-report.json").read_text(encoding="utf-8"))
    assert report["recommendation"] == "pause"
    assert report["runtime_errors"]
