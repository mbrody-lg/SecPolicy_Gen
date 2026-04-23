from unittest.mock import MagicMock, patch

import requests

from app.services.logic import run_validation_pipeline, send_policy_update_to_policy_agent


def test_send_policy_update_to_policy_agent_posts_expected_payload():
    response_payload = {
        "context_id": "ctx-1",
        "language": "en",
        "policy_text": "revised policy",
        "policy_agent_version": "0.2.0",
        "generated_at": "2026-03-05T01:00:00+00:00",
    }
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = response_payload

    with patch("app.services.logic.requests.post", return_value=response) as post:
        result = send_policy_update_to_policy_agent(
            context_id="ctx-1",
            language="en",
            policy_text="current policy",
            policy_agent_version="0.1.0",
            generated_at="2026-03-05T00:00:00+00:00",
            status="review",
            reasons=["Missing scope"],
            recommendations=["Add scope"],
        )

    assert result == response_payload
    post.assert_called_once_with(
        "http://policy-agent:5000/generate_policy/ctx-1/update",
        json={
            "context_id": "ctx-1",
            "language": "en",
            "policy_text": "current policy",
            "policy_agent_version": "0.1.0",
            "generated_at": "2026-03-05T00:00:00+00:00",
            "status": "review",
            "reasons": ["Missing scope"],
            "recommendations": ["Add scope"],
        },
        headers={"X-Correlation-ID": "ctx-1"},
        timeout=30.0,
    )


def test_send_policy_update_to_policy_agent_returns_deterministic_error():
    with patch(
        "app.services.logic.requests.post",
        side_effect=requests.exceptions.RequestException("boom"),
    ):
        result = send_policy_update_to_policy_agent(
            context_id="ctx-1",
            language="en",
            policy_text="current policy",
            policy_agent_version="0.1.0",
            generated_at="2026-03-05T00:00:00+00:00",
            status="review",
            reasons=["Missing scope"],
            recommendations=["Add scope"],
        )

    assert result == {
        "success": False,
        "error_type": "dependency_error",
        "error_code": "policy_update_request_failed",
        "message": "Error sending policy update to policy-agent.",
        "details": {
            "target_service": "policy-agent",
            "operation": "generate_policy_update",
            "request_fields": [
                "context_id",
                "language",
                "policy_text",
                "policy_agent_version",
                "generated_at",
                "status",
                "reasons",
                "recommendations",
            ],
        },
        "correlation_id": "ctx-1",
    }


def test_send_policy_update_to_policy_agent_surfaces_dependency_error_metadata(client):
    response = MagicMock()
    response.status_code = 400
    response.json.return_value = {
        "error_type": "contract_error",
        "error_code": "invalid_field_type",
        "correlation_id": "policy-corr",
    }
    http_error = requests.exceptions.HTTPError("boom")
    http_error.response = response

    with client.application.test_request_context("/validate-policy", method="POST"):
        with patch(
            "app.services.logic.requests.post",
            side_effect=http_error,
        ):
            result = send_policy_update_to_policy_agent(
                context_id="ctx-1",
                language="en",
                policy_text="current policy",
                policy_agent_version="0.1.0",
                generated_at="2026-03-05T00:00:00+00:00",
                status="review",
                reasons=["Missing scope"],
                recommendations=["Add scope"],
            )

    assert result == {
        "success": False,
        "error_type": "dependency_error",
        "error_code": "policy_update_request_failed",
        "message": "Error sending policy update to policy-agent.",
        "details": {
            "target_service": "policy-agent",
            "operation": "generate_policy_update",
            "dependency_status_code": 400,
            "dependency_error_type": "contract_error",
            "dependency_error_code": "invalid_field_type",
            "dependency_correlation_id": "policy-corr",
            "request_fields": [
                "context_id",
                "language",
                "policy_text",
                "policy_agent_version",
                "generated_at",
                "status",
                "reasons",
                "recommendations",
            ],
        },
        "correlation_id": "ctx-1",
    }


def test_run_validation_pipeline_returns_structured_success(client):
    payload = {
        "context_id": "ctx-1",
        "policy_text": "policy",
        "structured_plan": {"sections": []},
        "generated_at": "2026-03-05T00:00:00+00:00",
        "language": "en",
        "policy_agent_version": "0.1.0",
    }
    validation_result = {
        "status": "review",
        "policy_text": "updated policy",
        "language": "en",
        "generated_at": "2026-03-05T01:00:00+00:00",
        "policy_agent_version": "0.2.0",
        "reasons": ["Missing scope"],
        "recommendations": ["Add scope"],
        "evaluator_analysis": {"status": "review"},
    }

    with client.application.test_request_context("/validate-policy", method="POST"):
        with patch("app.services.logic.Coordinator") as coordinator_cls:
            coordinator_cls.return_value.validate_policy.return_value = validation_result
            result = run_validation_pipeline(payload)

    assert result == {
        "success": True,
        "stage": "completed",
        "validation": {
            "context_id": "ctx-1",
            "language": "en",
            "policy_text": "updated policy",
            "structured_plan": {"sections": []},
            "generated_at": "2026-03-05T01:00:00+00:00",
            "policy_agent_version": "0.2.0",
            "status": "review",
            "reasons": ["Missing scope"],
            "recommendations": ["Add scope"],
            "evaluator_analysis": {"status": "review"},
        },
    }


def test_run_validation_pipeline_returns_structured_contract_error(client):
    payload = {
        "context_id": "ctx-1",
        "policy_text": "policy",
    }

    with client.application.test_request_context("/validate-policy", method="POST"):
        result = run_validation_pipeline(payload)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "missing_required_fields",
        "message": "Required fields are missing.",
        "details": {
            "stage": "contract_validation",
            "missing_fields": ["structured_plan", "generated_at"],
        },
        "correlation_id": "ctx-1",
        "status_code": 400,
    }


def test_run_validation_pipeline_returns_structured_dependency_error(client):
    payload = {
        "context_id": "ctx-dep",
        "policy_text": "policy",
        "structured_plan": {"sections": []},
        "generated_at": "2026-03-05T00:00:00+00:00",
    }
    dependency_error = {
        "success": False,
        "error_type": "dependency_error",
        "error_code": "policy_update_request_failed",
        "message": "Error sending policy update to policy-agent.",
        "details": {"target_service": "policy-agent"},
        "correlation_id": "ctx-dep",
    }

    with client.application.test_request_context("/validate-policy", method="POST"):
        with patch("app.services.logic.Coordinator") as coordinator_cls:
            coordinator_cls.return_value.validate_policy.return_value = dependency_error
            result = run_validation_pipeline(payload)

    assert result == {
        "success": False,
        "error_type": "dependency_error",
        "error_code": "policy_update_request_failed",
        "message": "Error sending policy update to policy-agent.",
        "details": {"stage": "validation", "target_service": "policy-agent"},
        "correlation_id": "ctx-dep",
        "status_code": 502,
    }
