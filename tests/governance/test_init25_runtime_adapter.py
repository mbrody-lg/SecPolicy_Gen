import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.init25_runtime_adapter import (  # noqa: E402
    DockerAgentRuntimeAdapter,
    _EXPECTED_PROFILE_BODY,
    _profile_digest,
    _run_process_group,
)


CONFIG = ROOT / "agents" / "secpolicy_contract_dry_run.yaml"
PROFILE = ROOT / "agents" / "init25_shadow_permission_profile.json"


def _adapter(tmp_path, executor=None, profile=PROFILE):
    return DockerAgentRuntimeAdapter(CONFIG, profile, tmp_path, executor=executor)


def _invoke(adapter, **overrides):
    values = {
        "agent": "context_agent",
        "prompt": "bounded prompt",
        "correlation_id": "correlation-1",
        "input_artifact_ids": ["context.input.v1"],
        "expected_output_artifact_ids": ["context_agent.policy_handoff.v1"],
        "timeout": 1.0,
    }
    values.update(overrides)
    return adapter.invoke(**values)


def test_profile_is_exact_and_self_verifying():
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))

    assert {key: payload[key] for key in _EXPECTED_PROFILE_BODY} == _EXPECTED_PROFILE_BODY
    assert payload["integrity"] == {
        "algorithm": "sha256",
        "value": _profile_digest(_EXPECTED_PROFILE_BODY),
    }


def test_relaxed_profile_is_rejected_even_with_recomputed_digest(tmp_path):
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    payload["tools"]["allow"].append("filesystem")
    body = {key: payload[key] for key in _EXPECTED_PROFILE_BODY}
    payload["integrity"]["value"] = _profile_digest(body)
    relaxed = tmp_path / "relaxed.json"
    relaxed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="permission_profile_invalid"):
        _adapter(tmp_path / "output", profile=relaxed)


def test_simulation_uses_fixed_command_and_never_claims_live(tmp_path):
    captured = {}

    def executor(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}\n', stderr="")

    result = _invoke(_adapter(tmp_path, executor=executor))

    assert captured["command"] == [
        "docker", "agent", "run", str(CONFIG.resolve()), "--agent", "context_agent",
        "--exec", "--json", "--sandbox", "--no-kit", "-",
    ]
    invocation = result.runtime_invocation
    assert invocation["mode"] == "dry_run"
    assert invocation["runtime"] == "docker-agent-simulated"
    assert invocation["runtime_version"] == "simulated"
    assert invocation["exit_status"] == "simulated"
    assert invocation["output_artifact_ids"] == []
    assert set(invocation) == {
        "runtime", "runtime_version", "agent_config_ref", "agent_name", "mode",
        "input_artifact_ids", "output_artifact_ids", "permission_profile",
        "started_at", "finished_at", "exit_status", "logs_ref",
    }


def test_runtime_uses_ephemeral_home(tmp_path):
    captured = {}

    def executor(command, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    _invoke(_adapter(tmp_path, executor=executor))

    assert captured["HOME"] != os.environ.get("HOME")
    assert not Path(captured["HOME"]).exists()
    assert captured["DOCKER_AGENT_AUTO_INSTALL"] == "false"
    assert captured["DOCKER_AGENT_AUTO_UPDATE"] == "false"
    assert captured["TELEMETRY_ENABLED"] == "false"


def test_runtime_output_is_bounded_while_process_runs():
    result = _run_process_group(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 1100000); sys.stdout.flush()",
        ],
        prompt="",
        env=dict(os.environ),
        timeout=5,
    )

    assert result.error_code == "runtime_output_exceeded"
    assert result.stdout == ""


def test_sbx_absent_fails_closed_without_starting_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.init25_runtime_adapter.shutil.which", lambda *_args, **_kwargs: None)
    adapter = _adapter(tmp_path)

    result = _invoke(adapter)

    assert result.error_code == "sbx_unavailable"
    assert result.returncode == 126
    assert result.stdout == ""
    assert result.runtime_invocation["mode"] == "shadow"
    assert result.runtime_invocation["output_artifact_ids"] == []
    assert adapter.verify_logs_ref(result.runtime_invocation["logs_ref"])


def test_runtime_identity_drift_fails_closed_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.init25_runtime_adapter.shutil.which",
        lambda *_args, **_kwargs: "/sbx",
    )
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(
        adapter,
        "_runtime_identity",
        lambda *_args: ("v1.88.1", "0" * 40),
    )
    monkeypatch.setattr(
        "scripts.init25_runtime_adapter._run_process_group",
        lambda *_args, **_kwargs: pytest.fail("incompatible runtime was executed"),
    )

    result = _invoke(adapter)

    assert result.error_code == "runtime_incompatible"
    assert result.returncode == 1
    assert result.runtime_invocation["runtime_version"] == "v1.88.1"


def test_logs_are_allowlisted_and_canary_never_persisted(tmp_path):
    canary = "CANARY-SECRET-DO-NOT-PERSIST"

    def executor(command, **kwargs):
        assert canary in kwargs["input"]
        return subprocess.CompletedProcess(command, 1, stdout=canary, stderr=f"429 {canary}")

    adapter = _adapter(tmp_path, executor=executor)
    result = _invoke(adapter, prompt=canary)
    persisted = "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*") if path.is_file())

    assert result.error_code == "provider_quota_exceeded"
    assert canary not in persisted
    assert adapter.verify_logs_ref(result.runtime_invocation["logs_ref"])
    events = [json.loads(line) for line in (tmp_path / result.runtime_invocation["logs_ref"]["path"]).read_text().splitlines()]
    assert [event["event"] for event in events] == [
        "runtime.invocation.started", "runtime.invocation.finished"
    ]
    assert "error_code" not in events[0]
    assert events[1]["error_code"] == "provider_quota_exceeded"


def test_logs_ref_rejects_traversal_missing_file_and_digest_drift(tmp_path):
    adapter = _adapter(tmp_path, executor=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "ok", ""))
    logs_ref = _invoke(adapter).runtime_invocation["logs_ref"]

    traversal = dict(logs_ref, path="../outside.jsonl")
    assert not adapter.verify_logs_ref(traversal)
    assert not adapter.verify_logs_ref(dict(logs_ref, path="runtime-logs/missing.jsonl"))
    assert not adapter.verify_logs_ref(dict(logs_ref, sha256="0" * 64))
    path = tmp_path / logs_ref["path"]
    path.write_bytes(path.read_bytes() + b"x")
    assert not adapter.verify_logs_ref(logs_ref)


def test_runtime_invocation_hashes_config_and_profile(tmp_path):
    adapter = _adapter(tmp_path, executor=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "ok", ""))
    invocation = _invoke(adapter).runtime_invocation

    assert invocation["agent_config_ref"] == {
        "name": CONFIG.name,
        "sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
    }
    assert invocation["permission_profile"] == {
        "id": "init25.shadow.sandbox.v1",
        "sha256": _profile_digest(_EXPECTED_PROFILE_BODY),
    }


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_timeout_kills_the_real_process_group(tmp_path):
    pid_file = tmp_path / "pids"
    child = (
        "import os,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "open(sys.argv[1],'w').write(str(os.getpid())+' '+str(p.pid)); "
        "time.sleep(30)"
    )
    result = _run_process_group(
        [sys.executable, "-c", child, str(pid_file)],
        prompt="",
        env=dict(os.environ),
        timeout=0.25,
    )
    parent_pid, child_pid = map(int, pid_file.read_text().split())

    assert result.error_code == "runtime_timeout"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        alive = []
        for pid in (parent_pid, child_pid):
            stat = Path(f"/proc/{pid}/stat")
            if stat.exists():
                if stat.read_text().split()[2] != "Z":
                    alive.append(pid)
                continue
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            break
        time.sleep(0.05)
    assert not alive


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_deadline_must_be_finite_and_positive(tmp_path, timeout):
    adapter = _adapter(tmp_path, executor=lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="timeout_invalid"):
        _invoke(adapter, timeout=timeout)
