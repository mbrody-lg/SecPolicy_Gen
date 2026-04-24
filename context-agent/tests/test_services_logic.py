from types import SimpleNamespace

import pytest
import requests
from bson import ObjectId

from test_base import *
from app.services import logic


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def insert_one(self, document):
        self.docs.append(document)
        return SimpleNamespace(inserted_id=document.get("_id"))


class FakeDB:
    def __init__(self, contexts=None, interactions=None):
        self.contexts = FakeCollection(contexts)
        self.interactions = FakeCollection(interactions)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._payload


def test_get_context_and_prompt_prefers_context_refined_prompt(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "refined_prompt": "canonical refined prompt",
                "language": "es",
                "version": "1.2.3",
            }
        ],
        interactions=[
            {
                "context_id": context_id,
                "question_id": "refined_prompt",
                "answer": "legacy refined prompt",
            }
        ],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    assert payload["refined_prompt"] == "canonical refined prompt"
    assert payload["language"] == "es"
    assert payload["model_version"] == "1.2.3"


def test_get_context_and_prompt_falls_back_to_legacy_interaction(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[{"_id": context_id, "language": "en", "version": "0.2.0"}],
        interactions=[
            {
                "context_id": context_id,
                "question_id": "refined_prompt",
                "answer": "legacy refined prompt",
            }
        ],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    assert payload["refined_prompt"] == "legacy refined prompt"
    assert payload["language"] == "en"
    assert payload["model_version"] == "0.2.0"


def test_get_context_and_prompt_normalizes_numeric_model_version(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[{"_id": context_id, "refined_prompt": "prompt", "language": "en", "version": 1}],
        interactions=[],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    assert payload["model_version"] == "1"


def test_store_validated_policy_inserts_agent_interaction(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB()
    payload = {
        "policy_text": "Validated policy text",
        "generated_at": "2026-04-10T10:00:00+00:00",
        "policy_agent_version": "0.1.0",
        "language": "en",
        "status": "accepted",
        "recommendations": ["Keep evidence"],
    }

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.store_validated_policy(str(context_id), payload)

    assert result["success"] is True
    assert result["stage"] == "persistence"
    assert result["context_id"] == str(context_id)
    assert len(fake_db.interactions.docs) == 1
    stored = fake_db.interactions.docs[0]
    assert stored["context_id"] == context_id
    assert stored["question_id"] == "validated_policy"
    assert stored["answer"] == "Validated policy text"
    assert stored["policy_agent_version"] == "0.1.0"
    assert stored["language"] == "en"
    assert stored["status"] == "accepted"
    assert stored["recommendations"] == ["Keep evidence"]
    assert stored["ownership"] == {
        "owner_service": "context-agent",
        "source_of_truth": False,
        "view_type": "derived_policy_snapshot",
    }
    assert stored["policy_ref"] == {
        "owner_service": "policy-agent",
        "source_collection": "policies",
        "context_id": str(context_id),
    }
    assert stored["validation_ref"] == {
        "owner_service": "validator-agent",
        "source_collection": "validations",
        "context_id": str(context_id),
    }


def test_store_validated_policy_requires_full_payload(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB()

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.store_validated_policy(
            str(context_id),
            {
                "policy_text": "Validated policy text",
                "policy_agent_version": "0.1.0",
                "language": "en",
            },
        )

    assert exc_info.value.stage == "persistence"
    assert exc_info.value.error_code == "validated_policy_missing_fields"


def test_generate_full_policy_pipeline_stores_validated_policy_without_internal_http(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB()
    validated_payload = {
        "policy_text": "Validated policy text",
        "generated_at": "2026-04-10T10:00:00+00:00",
        "policy_agent_version": "0.1.0",
        "language": "en",
        "status": "review",
        "recommendations": ["Clarify retention period"],
    }

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        logic,
        "trigger_policy_generation",
        lambda current_context_id: {
            "success": True,
            "policy_data": {
                "context_id": current_context_id,
                "policy_text": "Draft policy text",
            },
        },
    )
    monkeypatch.setattr(logic, "call_validator_agent", lambda policy_data: validated_payload)

    def unexpected_http_call(*args, **kwargs):
        raise AssertionError("generate_full_policy_pipeline should not make internal HTTP callbacks")

    monkeypatch.setattr(logic.requests, "post", unexpected_http_call)

    result = logic.generate_full_policy_pipeline(str(context_id))

    assert result["success"] is True
    assert result["stage"] == "completed"
    assert result["validated_data"] == validated_payload
    assert result["persistence"]["stage"] == "persistence"
    assert len(fake_db.interactions.docs) == 1
    assert fake_db.interactions.docs[0]["answer"] == "Validated policy text"


def test_generate_full_policy_pipeline_returns_structured_stage_error(monkeypatch):
    monkeypatch.setattr(
        logic,
        "trigger_policy_generation",
        lambda context_id: {
            "success": False,
            "stage": "policy_generation",
            "error_type": "dependency_error",
            "error_code": "policy_agent_request_failed",
            "message": "Policy generation failed.",
            "details": {"target_service": "policy-agent"},
            "status_code": 502,
        },
    )

    result = logic.generate_full_policy_pipeline("ctx-1")

    assert result == {
        "success": False,
        "stage": "policy_generation",
        "error_type": "dependency_error",
        "error_code": "policy_agent_request_failed",
        "message": "Policy generation failed.",
        "details": {"target_service": "policy-agent"},
        "status_code": 502,
    }


def test_call_policy_agent_propagates_timeout_and_correlation_headers(app_context, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse({"success": True, "policy_text": "generated"})

    monkeypatch.setattr(logic.requests, "post", fake_post)
    logic.current_app.config["POLICY_AGENT_TIMEOUT_SECONDS"] = 12.5

    result = logic.call_policy_agent(
        {
            "context_id": "ctx-1",
            "correlation_id": "corr-1",
            "refined_prompt": "prompt",
            "language": "en",
            "model_version": "0.1.0",
        }
    )

    assert result == {"success": True, "policy_text": "generated"}
    assert captured["url"].endswith("/generate_policy")
    assert captured["headers"] == {"X-Correlation-ID": "corr-1"}
    assert captured["timeout"] == 12.5


def test_call_policy_agent_surfaces_dependency_error_metadata(app_context, monkeypatch):
    def fake_post(url, json, headers, timeout):
        return FakeResponse(
            {
                "success": False,
                "error_type": "contract_error",
                "error_code": "invalid_field_type",
                "correlation_id": "policy-corr",
            },
            status_code=400,
        )

    monkeypatch.setattr(logic.requests, "post", fake_post)

    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.call_policy_agent(
            {
                "context_id": "ctx-2",
                "refined_prompt": "prompt",
                "language": "en",
                "model_version": "0.1.0",
            }
        )

    assert exc_info.value.error_code == "policy_agent_request_failed"
    assert exc_info.value.correlation_id == "ctx-2"
    assert exc_info.value.details == {
        "target_service": "policy-agent",
        "operation": "generate_policy",
        "dependency_status_code": 400,
        "dependency_error_type": "contract_error",
        "dependency_error_code": "invalid_field_type",
        "dependency_correlation_id": "policy-corr",
    }


def test_call_validator_agent_propagates_timeout_and_correlation_headers(app_context, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse({"status": "accepted"})

    monkeypatch.setattr(logic.requests, "post", fake_post)
    logic.current_app.config["VALIDATOR_AGENT_TIMEOUT_SECONDS"] = 18.0

    result = logic.call_validator_agent(
        {
            "context_id": "ctx-3",
            "correlation_id": "corr-3",
            "policy_text": "policy",
            "structured_plan": [],
            "generated_at": "2026-04-22T00:00:00+00:00",
        }
    )

    assert result == {"status": "accepted"}
    assert captured["url"].endswith("/validate-policy")
    assert captured["headers"] == {"X-Correlation-ID": "corr-3"}
    assert captured["timeout"] == 18.0


def test_call_validator_agent_surfaces_dependency_error_metadata(app_context, monkeypatch):
    def fake_post(url, json, headers, timeout):
        return FakeResponse(
            {
                "success": False,
                "error_type": "dependency_error",
                "error_code": "policy_update_request_failed",
                "correlation_id": "validator-corr",
            },
            status_code=502,
        )

    monkeypatch.setattr(logic.requests, "post", fake_post)

    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.call_validator_agent(
            {
                "context_id": "ctx-4",
                "policy_text": "policy",
                "structured_plan": [],
                "generated_at": "2026-04-22T00:00:00+00:00",
            }
        )

    assert exc_info.value.error_code == "validator_agent_request_failed"
    assert exc_info.value.correlation_id == "ctx-4"
    assert exc_info.value.details == {
        "target_service": "validator-agent",
        "operation": "validate_policy",
        "dependency_status_code": 502,
        "dependency_error_type": "dependency_error",
        "dependency_error_code": "policy_update_request_failed",
        "dependency_correlation_id": "validator-corr",
    }
