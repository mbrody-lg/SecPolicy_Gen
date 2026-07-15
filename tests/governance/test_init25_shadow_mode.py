from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_init25_contract_dry_run import run_case  # noqa: E402
from scripts.run_init25_shadow_mode import (  # noqa: E402
    ExecutionResult,
    LEAF_AGENTS,
    MAX_OUTPUT_BYTES,
    OWNED_ARTIFACTS,
    _coerce_execution,
    detect_runtime_version,
    execute_subprocess,
    parse_stage_output,
    run_shadow_mode,
)


CASE_FILE = ROOT / "tests" / "fixtures" / "init25" / "dry_run_cases.json"


def _case(index=0):
    return deepcopy(json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"][index])


def _stage(agent, case, *, status="completed", correlation_id=None):
    _, baseline, _ = run_case(case)
    stage = {
        "case_id": case["case_id"],
        "correlation_id": correlation_id or baseline["correlation_id"],
        "status": status,
        "artifacts": {
            name: baseline["artifacts"][name]
            for name in OWNED_ARTIFACTS[agent]
            if name in baseline["artifacts"]
        },
        "runtime_errors": [],
        "security_findings": [],
    }
    if agent == "regulatory_rag_agent":
        stage["covered_evidence_families"] = baseline["covered_evidence_families"]
    if agent == "validator_agent":
        stage["validation_status"] = baseline["validation_status"]
    return stage


def test_parser_accepts_only_expected_agent_choice():
    payload = {"case_id": "case", "status": "completed"}
    stdout = "\n".join([
        json.dumps({"type": "user_message", "content": "do not persist"}),
        json.dumps({"type": "agent_choice", "agent_name": "other", "content": "{}"}),
        json.dumps({"type": "agent_choice", "agent_name": "context_agent", "content": json.dumps(payload)}),
    ])

    assert parse_stage_output(stdout, "context_agent") == payload


@pytest.mark.parametrize("stdout", ["not-json", "", json.dumps({"type": "agent_choice", "agent_name": "context_agent", "content": "[1]"})])
def test_parser_rejects_malformed_or_missing_stage_output(stdout):
    with pytest.raises(ValueError):
        parse_stage_output(stdout, "context_agent")


def test_simulation_is_never_reported_as_live_success():
    authoritative, candidate, report = run_shadow_mode(_case(), mode="simulated")

    assert authoritative["baseline_type"] == "deterministic_contract_baseline"
    assert authoritative["live_service_parity"] is False
    assert candidate["simulation_only"] is True
    assert candidate["provider_attempted"] is False
    assert candidate["provider_invoked"] is False
    assert "runtime_invocation" not in candidate
    assert report["recommendation"] == "pause"
    assert report["observability"]["has_runtime_invocation"] is False


def test_simulated_block_stops_downstream_agents():
    case = _case(2)
    calls = []

    def executor(command, **_kwargs):
        agent = command[command.index("--agent") + 1]
        calls.append(agent)
        return _stage(agent, case, status="blocked")

    _, candidate, report = run_shadow_mode(case, mode="simulated", executor=executor)

    assert calls == ["context_agent"]
    assert any(error["error_code"] == "stage_blocked" for error in candidate["runtime_errors"])
    assert report["recommendation"] == "pause"


def test_simulated_executor_uses_bounded_stdin_and_fixed_command():
    case = _case()
    calls = []

    def executor(command, **kwargs):
        agent = command[command.index("--agent") + 1]
        calls.append((command, json.loads(kwargs["input"])))
        return _stage(agent, case)

    run_shadow_mode(case, mode="simulated", executor=executor)

    assert [call[0][call[0].index("--agent") + 1] for call in calls] == list(LEAF_AGENTS)
    for command, request in calls:
        assert command[:3] == ["docker", "agent", "run"]
        assert Path(command[3]) == ROOT / "agents" / "secpolicy_contract_dry_run.yaml"
        assert command[-3:] == ["--exec", "--json", "-"]
        assert not {"--yolo", "--record", "--env-from-file", "--hooks"} & set(command)
        serialized = json.dumps(request)
        assert case["input"]["refined_context"] not in serialized
        assert case["input"]["policy_text"] not in serialized


def test_custom_executor_cannot_fabricate_live_evidence():
    with pytest.raises(ValueError, match="custom executor requires simulated mode"):
        run_shadow_mode(_case(), mode="live", executor=lambda *_args, **_kwargs: {})


def test_correlation_mismatch_is_bounded_and_stops():
    case = _case()
    calls = []

    def executor(command, **_kwargs):
        agent = command[command.index("--agent") + 1]
        calls.append(agent)
        return _stage(agent, case, correlation_id="wrong-correlation")

    _, candidate, report = run_shadow_mode(case, mode="simulated", executor=executor)

    assert calls == ["context_agent"]
    assert candidate["runtime_errors"][0]["error_code"] == "stage_identity_invalid"
    assert report["recommendation"] == "pause"


def test_candidate_field_drift_is_not_hidden_by_the_runner():
    case = _case()

    def executor(command, **_kwargs):
        agent = command[command.index("--agent") + 1]
        stage = _stage(agent, case)
        first_artifact = next(iter(stage["artifacts"]))
        stage["artifacts"][first_artifact] = stage["artifacts"][first_artifact][1:]
        return stage

    _, _, report = run_shadow_mode(case, mode="simulated", executor=executor)

    assert report["artifact_differences"]
    assert report["recommendation"] == "pause"


def test_provider_quota_error_is_redacted_to_bounded_code():
    result = subprocess.CompletedProcess([], 1, stdout="", stderr="429 quota CANARY-SECRET")

    stage, error = _coerce_execution(result, "context_agent")

    assert stage is None
    assert error == "provider_quota_exceeded"
    assert "CANARY-SECRET" not in json.dumps({"error_code": error})


def test_timeout_and_oversized_output_are_bounded():
    stage, error = _coerce_execution(ExecutionResult(error_code="runtime_timeout", returncode=1), "context_agent")
    assert stage is None
    assert error == "runtime_timeout"

    stage, error = _coerce_execution("x" * (MAX_OUTPUT_BYTES + 1), "context_agent")
    assert stage is None
    assert error == "runtime_failed"


def test_subprocess_timeout_includes_blocked_stdin():
    result = execute_subprocess(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        input="x" * MAX_OUTPUT_BYTES,
        env=dict(os.environ),
        timeout=0.05,
        max_output_bytes=MAX_OUTPUT_BYTES,
    )

    assert result.error_code == "runtime_timeout"


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_shadow_rejects_unbounded_timeout(timeout):
    with pytest.raises(ValueError, match="timeout must be finite and positive"):
        run_shadow_mode(_case(), mode="simulated", timeout=timeout)


def test_live_without_credentials_does_not_claim_provider_attempt(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _, candidate, report = run_shadow_mode(
        _case(),
        mode="live",
        version_detector=lambda: "v1.88.1",
    )

    assert candidate["provider_attempted"] is False
    assert candidate["provider_invoked"] is False
    assert report["recommendation"] == "pause"


def test_runtime_version_detection_keeps_home(monkeypatch):
    captured = {}

    def executor(command, **kwargs):
        captured.update(kwargs["env"])
        return ExecutionResult(stdout="docker agent version v1.88.1\n")

    monkeypatch.setenv("HOME", "/tmp/example-home")
    monkeypatch.setattr("scripts.run_init25_shadow_mode.execute_subprocess", executor)

    assert detect_runtime_version() == "v1.88.1"
    assert captured["HOME"] == "/tmp/example-home"


def test_cli_persists_only_bounded_summaries(tmp_path):
    case = _case()
    canary = "CANARY-DO-NOT-PERSIST"
    case["input"]["refined_context"] = canary
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_init25_shadow_mode.py",
            "--case-file",
            str(case_file),
            "--case-id",
            case["case_id"],
            "--output-dir",
            str(output_dir),
            "--mode",
            "simulated",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert {path.name for path in output_dir.iterdir()} == {
        "authoritative-summary.json",
        "candidate-summary.json",
        "parity-report.json",
    }
    assert canary not in "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir())
