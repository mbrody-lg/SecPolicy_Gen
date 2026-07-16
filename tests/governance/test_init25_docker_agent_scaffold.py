from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "agents" / "secpolicy_contract_dry_run.yaml"
CONTRACT_PATH = "docs/playbooks/target-agent-contract-pack.md"
COORDINATOR = "coordinator"
SPECIALISTS = {
    "context_agent",
    "regulatory_rag_agent",
    "policy_agent",
    "validator_agent",
}
EXPECTED_ARTIFACTS = {
    "context_agent": {"context_agent.policy_handoff.v1"},
    "regulatory_rag_agent": {
        "rag.retrieval_context",
        "rag.retrieval_plan",
        "rag.retrieval_evidence",
    },
    "policy_agent": {"policy_agent.policy_draft"},
    "validator_agent": {
        "validator.validation_payload",
        "validator.validation_decision",
    },
}
EXPECTED_EVIDENCE_FAMILIES = {
    "legal_norms",
    "sector_norms",
    "security_frameworks",
    "risk_methodologies",
    "implementation_guides",
}


def _config():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_init25_scaffold_uses_pinned_schema_and_named_yaml_model():
    config = _config()

    assert config["version"] == 10
    assert config["models"] == {
        "contract_model": {"provider": "openai", "model": "gpt-4o-mini"}
    }
    assert set(config["agents"]) == SPECIALISTS | {COORDINATOR}
    assert all(agent["model"] == "contract_model" for agent in config["agents"].values())


def test_init25_scaffold_has_only_the_coordinator_reasoning_tool():
    config = _config()
    serialized = CONFIG_PATH.read_text(encoding="utf-8")

    assert "${env." not in serialized
    assert "token_key" not in serialized
    assert "rag" not in config
    assert "mcps" not in config
    assert config["agents"][COORDINATOR]["toolsets"] == [{"type": "think"}]
    assert all("toolsets" not in config["agents"][name] for name in SPECIALISTS)


def test_init25_scaffold_coordinates_the_contract_team_and_stop_conditions():
    config = _config()
    coordinator = config["agents"][COORDINATOR]

    assert coordinator["sub_agents"] == [
        "context_agent",
        "regulatory_rag_agent",
        "policy_agent",
        "validator_agent",
    ]
    assert "structured_output" not in coordinator
    assert "Stop when a specialist returns blocked or failed" in coordinator["instruction"]
    assert all(CONTRACT_PATH in agent["instruction"] for agent in config["agents"].values())


def test_init25_specialists_have_closed_outputs_for_owned_artifacts():
    config = _config()

    for name, expected_artifacts in EXPECTED_ARTIFACTS.items():
        output = config["agents"][name]["structured_output"]
        schema = output["schema"]
        artifact_schema = schema["properties"]["artifacts"]

        assert output["strict"] is True
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert set(artifact_schema["properties"]) == expected_artifacts
        assert set(artifact_schema["required"]) == expected_artifacts

    rag_schema = config["agents"]["regulatory_rag_agent"]["structured_output"]["schema"]
    assert set(
        rag_schema["properties"]["covered_evidence_families"]["items"]["enum"]
    ) == EXPECTED_EVIDENCE_FAMILIES
