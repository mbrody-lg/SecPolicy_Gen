from datetime import datetime, timezone

import pytest

from app import mongo
from app.services import logic


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


def test_build_policy_update_prompt_is_deterministic():
    prompt = logic.build_policy_update_prompt(
        "Original policy",
        ["Missing controls"],
        ["Add MFA"],
    )

    assert "[Original Policy]:" in prompt
    assert "- Missing controls" in prompt
    assert "- Add MFA" in prompt
