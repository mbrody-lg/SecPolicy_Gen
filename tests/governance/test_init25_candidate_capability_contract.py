from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/init25-candidate-capabilities.yaml"


def test_candidate_contract_is_narrow_non_authoritative_and_blocked_by_init11():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    assert contract["status"] == "blocked_by_init_11_and_deadline_enforcement"
    assert contract["authority"] == "non_authoritative"
    assert contract["authentication"]["external_identity_headers_allowed"] is False
    assert {capability["path"] for capability in contract["capabilities"]} == {
        "/candidate/generate-policy",
        "/candidate/validate-policy",
    }
    assert all(capability["writes"] == [] for capability in contract["capabilities"])
    assert contract["activation"] == {
        "requires_verified_principal": True,
        "requires_deadline_enforcer": True,
    }
