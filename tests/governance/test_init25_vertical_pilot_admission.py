import json
from pathlib import Path

import yaml

from scripts.assess_init25_vertical_pilot import assess


ROOT = Path(__file__).resolve().parents[2]


def test_current_vertical_pilot_is_blocked_without_execution():
    result = assess()

    assert result["eligible"] is False
    assert result["pilot_executed"] is False
    assert result["next_action"] == "pause_runtime_expansion"
    assert result["blockers"] == sorted(result["checks"])


def test_vertical_pilot_is_admitted_only_when_every_gate_passes(tmp_path):
    contract = yaml.safe_load(
        (ROOT / "docs/contracts/init25-candidate-capabilities.yaml").read_text(encoding="utf-8")
    )
    contract["status"] = "active"
    contract["activation"] = {
        "requires_verified_principal": False,
        "requires_deadline_enforcer": False,
    }
    profile = json.loads(
        (ROOT / "agents/init25_shadow_permission_profile.json").read_text(encoding="utf-8")
    )
    profile["tools"] = {"allow": ["network", "service"], "deny": ["filesystem", "shell"]}
    config = yaml.safe_load(
        (ROOT / "agents/secpolicy_contract_dry_run.yaml").read_text(encoding="utf-8")
    )
    config["agents"]["coordinator"]["sub_agents"] = ["policy_agent", "validator_agent"]

    contract_path = tmp_path / "contract.yaml"
    profile_path = tmp_path / "profile.json"
    config_path = tmp_path / "config.yaml"
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    result = assess(contract_path, profile_path, config_path)

    assert result["eligible"] is True
    assert result["blockers"] == []
    assert result["next_action"] == "run_bounded_pilot"
