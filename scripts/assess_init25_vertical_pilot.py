#!/usr/bin/env python3
"""Assess whether the INIT-25 vertical pilot may run without weakening gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_CONTRACT = ROOT / "docs/contracts/init25-candidate-capabilities.yaml"
PERMISSION_PROFILE = ROOT / "agents/init25_shadow_permission_profile.json"
AGENT_CONFIG = ROOT / "agents/secpolicy_contract_dry_run.yaml"
EVIDENCE_MANIFEST = ROOT / "migration/init25/vertical-pilot-evidence.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}_invalid")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}_invalid")
    return payload


def _verified_evidence(manifest_path: Path, evidence_id: str) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        manifest = _load_json(manifest_path)
        entry = manifest.get("evidence", {}).get(evidence_id)
        artifact = (manifest_path.parent / entry["path"]).resolve(strict=True)
        artifact.relative_to(manifest_path.parent.resolve())
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return entry.get("status") == "passed" and entry.get("sha256") == digest


def assess(
    capability_contract: Path = CAPABILITY_CONTRACT,
    permission_profile: Path = PERMISSION_PROFILE,
    agent_config: Path = AGENT_CONFIG,
    evidence_manifest: Path = EVIDENCE_MANIFEST,
) -> dict[str, Any]:
    contract = _load_yaml(capability_contract)
    profile = _load_json(permission_profile)
    config = _load_yaml(agent_config)

    activation = contract.get("activation")
    tools = profile.get("tools")
    coordinator = config.get("agents", {}).get("coordinator", {})
    checks = {
        "candidate_ports_active": contract.get("status") == "active",
        "verified_principal_available": (
            isinstance(activation, dict)
            and activation.get("requires_verified_principal") is True
            and _verified_evidence(evidence_manifest, "verified_principal")
        ),
        "deadline_cancellation_available": (
            isinstance(activation, dict)
            and activation.get("requires_deadline_enforcer") is True
            and _verified_evidence(evidence_manifest, "deadline_cancellation")
        ),
        "service_network_allowlisted": (
            isinstance(tools, dict)
            and "network" in tools.get("allow", [])
            and "service" in tools.get("allow", [])
            and "network" not in tools.get("deny", [])
            and "service" not in tools.get("deny", [])
            and _verified_evidence(evidence_manifest, "service_network_permissions")
        ),
        "coordinator_scope_is_policy_validator_only": (
            coordinator.get("sub_agents") == ["policy_agent", "validator_agent"]
        ),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "1.0",
        "initiative": "INIT-25",
        "gate": "vertical_pilot_admission",
        "eligible": not blockers,
        "pilot_executed": False,
        "checks": checks,
        "blockers": blockers,
        "next_action": "run_bounded_pilot" if not blockers else "pause_runtime_expansion",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = assess()
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    raise SystemExit(0 if result["eligible"] else 2)


if __name__ == "__main__":
    main()
