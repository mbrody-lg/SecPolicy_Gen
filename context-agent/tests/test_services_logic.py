from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bson import ObjectId

from app.services import logic

pytestmark = [pytest.mark.fast]


def _install_fake_mongo(monkeypatch, context_doc=None, interaction_doc=None):
    fake_contexts = Mock()
    fake_interactions = Mock()

    def find_context(query):
        if context_doc and query == {"_id": context_doc["_id"]}:
            return context_doc
        return None

    def find_interaction(query):
        if interaction_doc and query == {
            "context_id": interaction_doc["context_id"],
            "question_id": "refined_prompt",
        }:
            return interaction_doc
        return None

    fake_contexts.find_one.side_effect = find_context
    fake_interactions.find_one.side_effect = find_interaction

    monkeypatch.setattr(
        logic,
        "mongo",
        SimpleNamespace(db=SimpleNamespace(contexts=fake_contexts, interactions=fake_interactions)),
    )


def test_get_context_and_prompt_happy_path(monkeypatch):
    context_id = "64b64b64b64b64b64b64b64b"
    context_obj_id = ObjectId(context_id)
    context_doc = {
        "_id": context_obj_id,
        "language": "es",
        "version": "2.4.1",
    }
    interaction_doc = {
        "context_id": context_obj_id,
        "question_id": "refined_prompt",
        "answer": "  Refined prompt ready for validation  ",
    }
    _install_fake_mongo(monkeypatch, context_doc=context_doc, interaction_doc=interaction_doc)

    result = logic.get_context_and_prompt(context_id)

    assert result["context_id"] == context_id
    assert result["refined_prompt"] == "Refined prompt ready for validation"
    assert result["language"] == "es"
    assert result["model_version"] == "2.4.1"
    assert result["generated_at"].endswith("+00:00")


def test_get_context_and_prompt_raises_lookuperror_when_refined_prompt_missing(monkeypatch):
    context_id = "64b64b64b64b64b64b64b64b"
    context_obj_id = ObjectId(context_id)
    context_doc = {
        "_id": context_obj_id,
        "language": "en",
        "version": "1.0.0",
    }
    _install_fake_mongo(monkeypatch, context_doc=context_doc, interaction_doc=None)

    with pytest.raises(LookupError, match="Refined prompt not found"):
        logic.get_context_and_prompt(context_id)


def test_trigger_policy_generation_happy_path(monkeypatch):
    payload = {
        "context_id": "64b64b64b64b64b64b64b64b",
        "refined_prompt": "Generate a policy",
        "language": "en",
        "model_version": "1.0.0",
        "generated_at": "2026-04-16T12:00:00+00:00",
    }
    policy_data = {"policy_text": "Generated policy", "status": "review"}
    get_context_and_prompt = Mock(return_value=payload)
    call_policy_agent = Mock(return_value=policy_data)

    monkeypatch.setattr(logic, "get_context_and_prompt", get_context_and_prompt)
    monkeypatch.setattr(logic, "call_policy_agent", call_policy_agent)

    result = logic.trigger_policy_generation(payload["context_id"])

    assert result == {"success": True, "policy_data": policy_data}
    get_context_and_prompt.assert_called_once_with(payload["context_id"])
    call_policy_agent.assert_called_once_with(payload)


def test_trigger_policy_generation_maps_downstream_failure_to_500(monkeypatch):
    payload = {
        "context_id": "64b64b64b64b64b64b64b64b",
        "refined_prompt": "Generate a policy",
        "language": "en",
        "model_version": "1.0.0",
        "generated_at": "2026-04-16T12:00:00+00:00",
    }
    monkeypatch.setattr(logic, "get_context_and_prompt", Mock(return_value=payload))
    monkeypatch.setattr(
        logic,
        "call_policy_agent",
        Mock(side_effect=RuntimeError("Error generating policy", "gateway timed out")),
    )

    result = logic.trigger_policy_generation(payload["context_id"])

    assert result["success"] is False
    assert result["error"] == "Error generating policy"
    assert result["details"] == "gateway timed out"
    assert result["status_code"] == 500


def test_generate_full_policy_pipeline_happy_path(monkeypatch):
    policy_result = {
        "success": True,
        "policy_data": {
            "policy_text": "Generated policy",
            "status": "review",
            "generated_at": "2026-04-16T12:00:00+00:00",
        },
    }
    validated_data = {
        "policy_text": "Validated policy",
        "status": "approved",
        "policy_agent_version": "1.2.3",
    }
    trigger_policy_generation = Mock(return_value=policy_result)
    call_validator_agent = Mock(return_value=validated_data)
    forward_validated_policy = Mock()

    monkeypatch.setattr(logic, "trigger_policy_generation", trigger_policy_generation)
    monkeypatch.setattr(logic, "call_validator_agent", call_validator_agent)
    monkeypatch.setattr(logic, "forward_validated_policy", forward_validated_policy)

    result = logic.generate_full_policy_pipeline("64b64b64b64b64b64b64b64b")

    assert result == {"success": True, "validated_data": validated_data}
    trigger_policy_generation.assert_called_once_with("64b64b64b64b64b64b64b64b")
    call_validator_agent.assert_called_once_with(policy_result["policy_data"])
    forward_validated_policy.assert_called_once_with("64b64b64b64b64b64b64b64b", validated_data)


def test_generate_full_policy_pipeline_maps_forwarding_failure_to_500(monkeypatch):
    policy_result = {
        "success": True,
        "policy_data": {
            "policy_text": "Generated policy",
            "status": "review",
            "generated_at": "2026-04-16T12:00:00+00:00",
        },
    }
    validated_data = {
        "policy_text": "Validated policy",
        "status": "approved",
        "policy_agent_version": "1.2.3",
    }
    monkeypatch.setattr(logic, "trigger_policy_generation", Mock(return_value=policy_result))
    monkeypatch.setattr(logic, "call_validator_agent", Mock(return_value=validated_data))
    monkeypatch.setattr(
        logic,
        "forward_validated_policy",
        Mock(side_effect=RuntimeError("Error saving validated policy", "database offline")),
    )

    result = logic.generate_full_policy_pipeline("64b64b64b64b64b64b64b64b")

    assert result["success"] is False
    assert result["error"] == "Policy generation failed."
    assert result["details"] == "database offline"
    assert result["status_code"] == 500
