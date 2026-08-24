from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import mongo
from app.agents.factory import MAX_PROPOSALS, validate_agent_config
from app.services import logic


def _config() -> dict:
    return {
        "type": "openai",
        "name": "Policy Agent",
        "instructions": "Generate a security policy.",
        "model": "configured-model",
        "roles": [
            {
                "IMQ": "Incremental query",
                "instructions": "Return the final policy.",
                "model": "configured-model",
                "temperature": 0.5,
                "max_tokens": 1000,
            }
        ],
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda config: config.update(model=" "), "model.*non-empty"),
        (lambda config: config.update(roles=[]), "roles.*non-empty"),
        (
            lambda config: config["roles"][0].update(model="different-model"),
            "model must match",
        ),
        (lambda config: config["roles"][0].update(temperature=True), "temperature"),
        (lambda config: config["roles"][0].update(temperature=2.1), "temperature"),
        (lambda config: config["roles"][0].update(max_tokens=0), "max_tokens"),
        (
            lambda config: config["roles"][0].update(proposals=MAX_PROPOSALS + 1),
            "proposals",
        ),
        (
            lambda config: config["roles"].append(deepcopy(config["roles"][0])),
            "only be configured once",
        ),
    ],
)
def test_validate_agent_config_rejects_invalid_provider_settings(mutate, message):
    config = _config()
    mutate(config)

    with pytest.raises(ValueError, match=message):
        validate_agent_config(config)


def test_validate_agent_config_accepts_role_identifier_in_any_key_order():
    config = _config()
    config["roles"] = [
        {
            "instructions": "Return the final policy.",
            "IMQ": "Incremental query",
            "max_tokens": 1,
            "temperature": 0,
        }
    ]

    assert validate_agent_config(config) is config


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _run_generation(monkeypatch, provider: FakeProvider) -> dict:
    monkeypatch.setattr(logic, "load_policy_config", _config)
    monkeypatch.setattr("app.agents.openai.agent.OpenAIClient", lambda: provider)
    return logic.run_generation_pipeline(
        {
            "context_id": "provider-config-context",
            "refined_prompt": "Generate the policy.",
            "language": "en",
            "model_version": "context-contract-v1",
        }
    )


def test_called_and_persisted_model_come_from_top_level_yaml(app_context, monkeypatch):
    provider = FakeProvider(
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Generated policy"))]
        )
    )

    result = _run_generation(monkeypatch, provider)

    assert result["success"] is True
    assert provider.calls[0]["model"] == "configured-model"
    assert result["policy"]["model_version"] == "context-contract-v1"
    assert result["policy"]["provider_provenance"] == {
        "provider": "openai",
        "model": "configured-model",
    }
    stored_config = mongo.db.policy_configs.find_one(
        {"model_version": "context-contract-v1"}
    )
    assert stored_config["provider_provenance"] == result["policy"]["provider_provenance"]


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace(message=None)]),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="   "))]
        ),
    ],
)
def test_invalid_provider_response_makes_no_database_writes(
    app_context, monkeypatch, response
):
    result = _run_generation(monkeypatch, FakeProvider(response))

    assert result["success"] is False
    assert result["error_code"] == "policy_generation_failed"
    assert mongo.db.policies.count_documents({}) == 0
    assert mongo.db.policy_configs.count_documents({}) == 0


def test_blank_backend_result_makes_no_config_write(app_context, monkeypatch):
    class BlankAgent:
        roles = [{"IMQ": "Incremental query"}]

        def run(self, *_args, **_kwargs):
            return {"text": " "}

    monkeypatch.setattr(logic, "load_policy_config", _config)
    monkeypatch.setattr(logic, "create_agent_from_config", lambda _config: BlankAgent())

    result = logic.run_generation_pipeline(
        {
            "context_id": "blank-backend-context",
            "refined_prompt": "Generate the policy.",
            "language": "en",
            "model_version": "context-contract-v1",
        }
    )

    assert result["success"] is False
    assert mongo.db.policies.count_documents({}) == 0
    assert mongo.db.policy_configs.count_documents({}) == 0


def test_invalid_provider_update_preserves_policy_and_config(app_context, monkeypatch):
    context_id = "provider-update-context"
    mongo.db.policies.insert_one(
        {
            "context_id": context_id,
            "language": "en",
            "policy_text": "Original policy",
            "structured_plan": [],
            "model_version": "context-contract-v1",
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc),
        }
    )
    before = mongo.db.policies.find_one({"context_id": context_id})
    monkeypatch.setattr(logic, "load_policy_config", _config)
    monkeypatch.setattr(
        "app.agents.openai.agent.OpenAIClient",
        lambda: FakeProvider(SimpleNamespace(choices=[])),
    )

    result = logic.run_policy_update_pipeline(
        {
            "context_id": context_id,
            "language": "en",
            "policy_text": "Original policy",
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "review",
            "reasons": ["Missing detail"],
            "recommendations": ["Add detail"],
        },
        context_id,
    )

    assert result["success"] is False
    assert mongo.db.policies.find_one({"context_id": context_id}) == before
    assert mongo.db.policy_configs.count_documents({}) == 0
