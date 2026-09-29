"""Local bootstrap must not reuse public deterministic workload fixtures."""

import importlib.util
import json
import stat
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "provision_local_workload_keys.py"


def _module():
    spec = importlib.util.spec_from_file_location("provision_local_workload_keys", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provision_fresh_separate_caller_keys(tmp_path):
    env = tmp_path / ".env"
    candidate = tmp_path / ".env.candidate.local"
    env.write_text("TESTING=false\nWORKLOAD_CONTEXT_SIGNING_KID=context-test-v1\n")
    module = _module()
    module.provision(env, candidate, "organization-a")
    settings = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line)
    candidate_settings = dict(line.split("=", 1) for line in candidate.read_text().splitlines())
    assert settings["TESTING"] == "false"
    assert settings["WORKLOAD_CONTEXT_SIGNING_KID"] == "context-local-v1"
    assert "WORKLOAD_CANDIDATE_SIGNING_PRIVATE_KEY_B64" not in settings
    assert "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64" not in candidate_settings
    assert len({settings["WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64"], settings["WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64"], candidate_settings["WORKLOAD_CANDIDATE_SIGNING_PRIVATE_KEY_B64"]}) == 3
    for name in ("CONTEXT", "VALIDATOR", "CANDIDATE"):
        registry = json.loads(settings[f"WORKLOAD_{name}_VERIFY_KEYS"])
        assert list(registry.values())[0]["tenant_ids"] == ["organization-a"]
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert stat.S_IMODE(candidate.stat().st_mode) == 0o600


@pytest.mark.parametrize("tenant", ["", "a b", "x" * 65])
def test_reject_invalid_tenant_without_writing(tmp_path, tenant):
    env = tmp_path / ".env"
    with pytest.raises(ValueError):
        _module().provision(env, tmp_path / ".env.candidate.local", tenant)
    assert not env.exists()


def test_existing_world_readable_env_is_atomically_replaced_private(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TESTING=false\n")
    env.chmod(0o644)
    _module().provision(env, tmp_path / ".env.candidate.local", "tenant-a")
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_reject_same_destination_without_modifying_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("sentinel\n")
    with pytest.raises(ValueError):
        _module().provision(env, env, "tenant-a")
    assert env.read_text() == "sentinel\n"


def test_reject_symlink_destination_without_modifying_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("sentinel\n")
    env = tmp_path / ".env"
    env.symlink_to(target)
    with pytest.raises(ValueError):
        _module().provision(env, tmp_path / ".env.candidate.local", "tenant-a")
    assert target.read_text() == "sentinel\n"


def test_failure_preparing_second_destination_cleans_first_secret_temp(tmp_path):
    env = tmp_path / ".env"
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    with pytest.raises(OSError):
        _module().provision(env, blocker / ".env.candidate.local", "tenant-a")
    assert not env.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["blocker"]
