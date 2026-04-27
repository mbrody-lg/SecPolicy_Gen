from datetime import datetime, timezone

import pytest
from flask import g

from app import mongo
from app.services import logic


def test_get_health_status_returns_lightweight_payload():
    assert logic.get_health_status() == {
        "status": "ok",
        "service": "policy-agent",
    }


def test_get_readiness_status_returns_ready_when_dependencies_are_available(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["normativa"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setenv("CHROMA_HOST", "chroma")
    monkeypatch.setenv("CHROMA_PORT", "8000")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["config"]["status"] == "ok"
    assert payload["checks"]["mongo"]["status"] == "ok"
    assert payload["checks"]["chroma"] == {
        "status": "configured",
        "mode": "config_only",
        "collection_count": 1,
    }


def test_get_readiness_status_reports_controlled_failure(app, monkeypatch):
    class FailingAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            raise RuntimeError("mongo unavailable")

    class FailingMongoClient:
        admin = FailingAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["normativa"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FailingMongoClient())
    monkeypatch.setenv("CHROMA_PORT", "not-a-number")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["config"]["status"] == "ok"
    assert payload["checks"]["mongo"]["reason"] == "ping_failed"
    assert payload["checks"]["chroma"]["status"] == "error"
    assert payload["checks"]["chroma"]["mode"] == "config_only"
    assert "details" not in payload["checks"]["mongo"]
    assert "details" not in payload["checks"]["chroma"]


def test_get_readiness_status_reads_yaml_style_chroma_vector_entry(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": "Chroma Vector Database",
                            "collection": ["normativa", "sector", "metodologia", "guia"],
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setenv("CHROMA_PORT", "8000")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 200
    assert payload["checks"]["chroma"] == {
        "status": "configured",
        "mode": "config_only",
        "collection_count": 4,
    }


def test_run_generation_pipeline_rejects_invalid_json_body(app_context):
    result = logic.run_generation_pipeline(None)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "invalid_json_body",
        "message": "Request body must be a JSON object.",
        "details": {"stage": "contract_validation", "expected_type": "object"},
        "status_code": 400,
    }


def test_run_generation_pipeline_rejects_oversized_prompt(app_context):
    payload = {
        "context_id": "ctx-oversized",
        "refined_prompt": "x" * (logic.MAX_PROMPT_LENGTH + 1),
        "language": "en",
        "model_version": "openai",
    }

    result = logic.run_generation_pipeline(payload)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "field_too_large",
        "message": "Field 'refined_prompt' exceeds the allowed size.",
        "details": {
            "stage": "contract_validation",
            "field": "refined_prompt",
            "max_length": logic.MAX_PROMPT_LENGTH,
        },
        "correlation_id": "ctx-oversized",
        "status_code": 413,
    }


def test_validate_generation_payload_accepts_optional_business_context(app_context):
    result = logic.validate_generation_payload(
        {
            "context_id": "ctx-business",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
            "business_context": {
                "country": "Spain",
                "sector": "Private healthcare",
                "important_assets": ["Medical records", "Backups"],
            },
        }
    )

    assert result["business_context"] == {
        "country": "Spain",
        "sector": "Private healthcare",
        "important_assets": ["Medical records", "Backups"],
    }


def test_validate_generation_payload_rejects_invalid_business_context(app_context):
    result = logic.run_generation_pipeline(
        {
            "context_id": "ctx-business",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
            "business_context": "country=Spain",
        }
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_field_type"
    assert result["details"]["field"] == "business_context"


def test_validate_generation_payload_rejects_nested_business_context_list(app_context):
    result = logic.run_generation_pipeline(
        {
            "context_id": "ctx-business",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
            "business_context": {
                "important_assets": ["Medical records", {"name": "Backups"}],
            },
        }
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_field_type"
    assert result["details"]["field"] == "business_context"
    assert result["details"]["key"] == "important_assets"


def test_run_generation_pipeline_persists_policy(app_context, monkeypatch):
    monkeypatch.setattr(
        logic,
        "run_with_agent",
        lambda **kwargs: {"text": "Generated policy body", "structured_plan": ["scope"]},
    )

    result = logic.run_generation_pipeline(
        {
            "context_id": "ctx-1",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
        }
    )

    assert result["success"] is True
    assert result["stage"] == "completed"
    assert result["policy"]["policy_text"] == "Generated policy body"
    stored_policy = mongo.db.policies.find_one({"context_id": "ctx-1"})
    assert stored_policy is not None
    assert stored_policy["ownership"]["owner_service"] == "policy-agent"
    assert stored_policy["correlation_id"] == "ctx-1"


def test_run_generation_pipeline_emits_structured_logs(app_context, monkeypatch, caplog):
    monkeypatch.setattr(
        logic,
        "run_with_agent",
        lambda **kwargs: {"text": "Generated policy body", "structured_plan": ["scope"]},
    )

    with caplog.at_level("INFO"):
        result = logic.run_generation_pipeline(
            {
                "context_id": "ctx-log",
                "refined_prompt": "Generate policy",
                "language": "en",
                "model_version": "openai",
            }
        )

    assert result["success"] is True
    assert '"event": "policy.pipeline.generation_completed"' in caplog.text
    assert '"context_id": "ctx-log"' in caplog.text


def test_run_policy_update_pipeline_rejects_oversized_feedback_list(app_context):
    context_id = "ctx-update"
    mongo.db.policies.insert_one(
        {
            "_id": "policy-1",
            "context_id": context_id,
            "language": "en",
            "policy_text": "previous policy",
            "structured_plan": [],
            "model_version": "gpt-4",
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc),
        }
    )
    payload = {
        "context_id": context_id,
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": [f"reason-{idx}" for idx in range(logic.MAX_FEEDBACK_ITEMS + 1)],
        "recommendations": ["recommendation"],
    }

    result = logic.run_policy_update_pipeline(payload, context_id)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "field_too_large",
        "message": "Field 'reasons' exceeds the allowed item count.",
        "details": {
            "stage": "contract_validation",
            "field": "reasons",
            "max_items": logic.MAX_FEEDBACK_ITEMS,
        },
        "correlation_id": context_id,
        "status_code": 413,
    }


def test_run_policy_update_pipeline_updates_existing_policy(app_context, monkeypatch):
    context_id = "ctx-existing"
    mongo.db.policies.insert_one(
        {
            "_id": "policy-2",
            "context_id": context_id,
            "language": "en",
            "policy_text": "previous policy",
            "structured_plan": ["old"],
            "model_version": "gpt-4",
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc),
            "revision_count": 1,
        }
    )
    monkeypatch.setattr(
        logic,
        "update_with_agent",
        lambda **kwargs: {"text": "Updated policy body"},
    )
    payload = {
        "context_id": context_id,
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": ["reason"],
        "recommendations": ["recommendation"],
    }

    result = logic.run_policy_update_pipeline(payload, context_id)

    assert result["success"] is True
    assert result["policy"]["policy_text"] == "Updated policy body"
    assert result["policy"]["revision_count"] == 2
    stored_policy = mongo.db.policies.find_one({"context_id": context_id})
    assert stored_policy["policy_text"] == "Updated policy body"
    assert stored_policy["last_validation_status"] == "review"
    assert stored_policy["correlation_id"] == context_id


def test_build_policy_update_prompt_is_deterministic():
    prompt = logic.build_policy_update_prompt(
        "Original policy",
        ["Missing controls"],
        ["Add MFA"],
    )

    assert "[Original Policy]:" in prompt
    assert "- Missing controls" in prompt
    assert "- Add MFA" in prompt


def test_validate_generation_payload_prefers_request_correlation_id(app):
    payload = {
        "context_id": "ctx-from-payload",
        "refined_prompt": "Generate policy",
        "language": "en",
        "model_version": "openai",
    }

    with app.test_request_context(headers={"X-Correlation-ID": "ctx-from-header"}):
        g.correlation_id = "ctx-from-header"
        result = logic.validate_generation_payload(payload)

    assert result["correlation_id"] == "ctx-from-header"


def test_run_with_agent_propagates_request_correlation_id(app, monkeypatch):
    class FakeConfiguredClient:
        def __init__(self, headers):
            self.default_headers = headers
            self.chat = object()

    class FakeSdkClient:
        def __init__(self):
            self.calls = []

        def with_options(self, *, default_headers):
            self.calls.append(default_headers)
            return FakeConfiguredClient(default_headers)

    class FakeClientWrapper:
        def __init__(self, sdk_client):
            self.client = sdk_client
            self.chat = object()

    class FakeAgent:
        def __init__(self, sdk_client):
            self.client = FakeClientWrapper(sdk_client)
            self.roles = [{"PolicyGeneration": True}]

        def run(self, prompt, context_id=None, retrieval_plan=None):
            return {
                "text": "Generated policy body",
                "structured_plan": [],
                "used_headers": self.client.client.default_headers,
                "context_id": context_id,
                "retrieval_plan": retrieval_plan,
            }

    sdk_client = FakeSdkClient()
    fake_agent = FakeAgent(sdk_client)
    monkeypatch.setattr(logic, "load_policy_config", lambda: {"type": "mock", "name": "fake", "instructions": "", "model": "fake", "roles": [{"MPG": "unused", "instructions": "x"}]})
    monkeypatch.setattr(logic, "_store_policy_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(logic, "create_agent_from_config", lambda config: fake_agent)

    with app.test_request_context(headers={"X-Correlation-ID": "outbound-correlation-id"}):
        g.correlation_id = "outbound-correlation-id"
        result = logic.run_with_agent(
            refined_prompt="Generate policy",
            context_id="ctx-123",
            model_version="openai",
        )

    assert sdk_client.calls == [{"X-Correlation-ID": "outbound-correlation-id"}]
    assert result["used_headers"] == {"X-Correlation-ID": "outbound-correlation-id"}
