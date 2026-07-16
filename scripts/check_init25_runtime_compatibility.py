#!/usr/bin/env python3
"""Verify the pinned Docker Agent binary and initialize the INIT-25 config."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "agents" / "docker-agent-runtime.lock.json"
DEFAULT_CONFIG = ROOT / "agents" / "secpolicy_contract_dry_run.yaml"


def _fail(message: str) -> None:
    raise SystemExit(f"INIT-25 runtime compatibility error: {message}")


def _load_lock(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "commit",
        "schema_version",
        "assets",
    }:
        _fail("runtime lock is invalid")
    return payload


def _parse_identity(output: str) -> tuple[str, str]:
    version = re.search(r"\bversion\s+(v\d+\.\d+\.\d+)\b", output)
    commit = re.search(r"^Commit:\s+([0-9a-f]{40})$", output, re.MULTILINE)
    if not version or not commit:
        _fail("runtime identity is invalid")
    return version.group(1), commit.group(1)


def check_runtime(binary: Path | None, lock_path: Path, config_path: Path) -> dict[str, Any]:
    lock = _load_lock(lock_path)
    config = config_path.read_text(encoding="utf-8")
    schema = re.search(r"^version:\s*(\d+)\s*$", config, re.MULTILINE)
    if not schema or int(schema.group(1)) != lock["schema_version"]:
        _fail("config schema does not match runtime lock")

    prefix = [str(binary)] if binary else ["docker", "agent"]
    with tempfile.TemporaryDirectory(prefix="init25-runtime-compat-") as runtime_root:
        root = Path(runtime_root)
        home = root / "home"
        home.mkdir()
        env = {
            key: os.environ[key]
            for key in ("PATH", "SSL_CERT_DIR", "SSL_CERT_FILE")
            if key in os.environ
        }
        env.update({
            "DOCKER_AGENT_AUTO_INSTALL": "false",
            "DOCKER_AGENT_AUTO_UPDATE": "false",
            "HOME": str(home),
            "OPENAI_API_KEY": "init25-compatibility-probe-not-a-secret",
            "TELEMETRY_ENABLED": "false",
        })
        try:
            identity = subprocess.run(
                [*prefix, "version"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail("runtime unavailable")
        if identity.returncode:
            _fail("runtime version command failed")
        version, commit = _parse_identity(identity.stdout)
        if version != lock["version"] or commit != lock["commit"]:
            _fail(
                f"expected {lock['version']} ({lock['commit']}), "
                f"found {version} ({commit})"
            )

        command = [
            *prefix,
            "--config-dir", str(root / "config"),
            "--data-dir", str(root / "data"),
            "--cache-dir", str(root / "cache"),
            "run", str(config_path),
            "--agent", "coordinator",
            "--dry-run", "--exec", "--json", "--no-kit",
        ]
        try:
            probe = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail("runtime dry-run failed")
    if probe.returncode:
        _fail("runtime rejected the pinned config")
    return {
        "version": version,
        "commit": commit,
        "schema_version": lock["schema_version"],
        "config": config_path.relative_to(ROOT).as_posix(),
        "compatible": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(check_runtime(args.binary, args.lock, args.config), sort_keys=True))


if __name__ == "__main__":
    main()
