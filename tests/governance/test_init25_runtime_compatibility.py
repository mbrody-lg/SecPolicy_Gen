import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_init25_runtime_compatibility import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_LOCK,
    check_runtime,
)

WORKFLOW = ROOT / ".github" / "workflows" / "init25-runtime-compatibility.yml"


def _fake_runtime(tmp_path: Path, version: str, commit: str) -> Path:
    binary = tmp_path / "docker-agent"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        f"VERSION = {version!r}\n"
        f"COMMIT = {commit!r}\n"
        "env = os.environ\n"
        "assert env['DOCKER_AGENT_AUTO_INSTALL'] == 'false'\n"
        "assert env['DOCKER_AGENT_AUTO_UPDATE'] == 'false'\n"
        "assert env['OPENAI_API_KEY'] == 'init25-compatibility-probe-not-a-secret'\n"
        "assert not {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'} & set(env)\n"
        "if sys.argv[1:] == ['version']:\n"
        "    print(f'docker agent version {VERSION}')\n"
        "    print(f'Commit: {COMMIT}')\n"
        "    raise SystemExit(0)\n"
        "required = {'--dry-run', '--exec', '--json', '--no-kit'}\n"
        "raise SystemExit(0 if required.issubset(sys.argv) else 2)\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def test_init25_runtime_lock_matches_config_schema_reference():
    lock = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    config = DEFAULT_CONFIG.read_text(encoding="utf-8")

    assert lock["version"] in config.splitlines()[0]
    assert f"version: {lock['schema_version']}" in config
    assert set(lock["assets"]) == {"darwin-arm64", "linux-amd64"}
    assert all(len(digest) == 64 for digest in lock["assets"].values())


def test_init25_runtime_workflow_uses_locked_linux_asset():
    lock = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert lock["version"] in workflow
    assert lock["assets"]["linux-amd64"] in workflow


def test_init25_runtime_probe_accepts_exact_pinned_identity(tmp_path):
    lock = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    binary = _fake_runtime(tmp_path, lock["version"], lock["commit"])

    result = check_runtime(binary, DEFAULT_LOCK, DEFAULT_CONFIG)

    assert result["compatible"] is True
    assert result["version"] == lock["version"]
    assert result["commit"] == lock["commit"]


def test_init25_runtime_probe_rejects_version_drift(tmp_path):
    lock = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    binary = _fake_runtime(tmp_path, "v1.88.1", lock["commit"])

    with pytest.raises(SystemExit, match="expected v1.110.0"):
        check_runtime(binary, DEFAULT_LOCK, DEFAULT_CONFIG)


def test_init25_runtime_probe_rejects_schema_drift(tmp_path):
    lock = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    lock["schema_version"] = 999
    drifted_lock = tmp_path / "runtime.lock.json"
    drifted_lock.write_text(json.dumps(lock), encoding="utf-8")
    binary = _fake_runtime(tmp_path, lock["version"], lock["commit"])

    with pytest.raises(SystemExit, match="config schema does not match runtime lock"):
        check_runtime(binary, drifted_lock, DEFAULT_CONFIG)
