from unittest.mock import MagicMock, patch

import requests

from app.services.logic import (
    get_health_status,
    get_readiness_status,
    run_validation_pipeline,
    send_policy_update_to_policy_agent,
)


def test_get_health_status_returns_service_payload():
    assert get_health_status() == {
        "status": "ok",
        "service": "validator-agent",
    }


def test_get_readiness_status_returns_ready_payload(app, monkeypatch):
    ping_mock = MagicMock()
    monkeypatch.setattr("app.services.logic.mongo.db.command", ping_mock)

    with app.test_request_context("/ready", headers={"X-Correlation-ID": "corr-ready"}):
        result = get_readiness_status()

    ping_mock.assert_called_once_with("ping")
    assert result == {
        "success": True,
        "status": "ready",
        "service": "validator-agent",
        "checks": {"mongo": "ok", "config": "ok"},
    }


def test_get_readiness_status_returns_dependency_error_when_mongo_fails(app, monkeypatch):
    command_mock = MagicMock(side_effect=RuntimeError("mongo down"))
    monkeypatch.setattr("app.services.logic.mongo.db.command", command_mock)

    with app.test_request_context("/ready", headers={"X-Correlation-ID": "corr-ready"}):
        result = get_readiness_status()

    assert result == {
        "success": False,
        "error_type": "dependency_error",
        "error_code": "service_not_ready",
        "message": "Validator-agent readiness checks failed.",
        "details": {
            "checks": {"mongo": "error", "config": "ok"},
            "errors": ["mongo_unavailable"],
        },
        "status_code": 503,
    }


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


def test_send_policy_update_to_policy_agent_prefers_request_correlation_id(client):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"policy_text": "revised"}

    with client.application.test_request_context(
        "/validate-policy",
        method="POST",
        headers={"X-Correlation-ID": "corr-request"},
    ):
        with patch("app.services.logic.requests.post", return_value=response) as post:
            send_policy_update_to_policy_agent(
                context_id="ctx-1",
                language="en",
                policy_text="current policy",
                policy_agent_version="0.1.0",
                generated_at="2026-03-05T00:00:00+00:00",
                status="review",
                reasons=["Missing scope"],
                recommendations=["Add scope"],
            )

    assert post.call_args.kwargs["headers"] == {"X-Correlation-ID": "corr-request"}


def test_send_policy_update_to_policy_agent_emits_structured_logs(caplog):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.status_code = 200
    response.json.return_value = {"policy_text": "revised"}

    with patch("app.services.logic.requests.post", return_value=response):
        with caplog.at_level("INFO"):
            send_policy_update_to_policy_agent(
                context_id="ctx-log",
                language="en",
                policy_text="current policy",
                policy_agent_version="0.1.0",
                generated_at="2026-03-05T00:00:00+00:00",
                status="review",
                reasons=["Missing scope"],
                recommendations=["Add scope"],
            )

    assert '"event": "validator.policy_update.request"' in caplog.text
    assert '"event": "validator.policy_update.response"' in caplog.text
    assert '"context_id": "ctx-log"' in caplog.text


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
            "retrieval_evidence": [],
            "generated_at": "2026-03-05T01:00:00+00:00",
            "policy_agent_version": "0.2.0",
            "status": "review",
            "reasons": ["Missing scope"],
            "recommendations": ["Add scope"],
            "evaluator_analysis": {"status": "review"},
        },
    }


def test_run_validation_pipeline_passes_retrieval_evidence_to_coordinator(client):
    evidence = [
        {
            "citation": "normativa:rgpd",
            "source_id": "normativa",
            "collection": "normativa",
            "family": "legal_norms",
            "text": "Article 32 requires appropriate security.",
        }
    ]
    payload = {
        "context_id": "ctx-evidence",
        "policy_text": "policy",
        "structured_plan": {"sections": []},
        "retrieval_evidence": evidence,
        "generated_at": "2026-03-05T00:00:00+00:00",
    }
    validation_result = {
        "status": "accepted",
        "policy_text": "policy",
        "reasons": [],
        "recommendations": [],
        "retrieval_evidence": evidence,
    }

    with client.application.test_request_context("/validate-policy", method="POST"):
        with patch("app.services.logic.Coordinator") as coordinator_cls:
            coordinator_cls.return_value.validate_policy.return_value = validation_result
            result = run_validation_pipeline(payload)

    coordinator_cls.return_value.validate_policy.assert_called_once()
    normalized_payload = coordinator_cls.return_value.validate_policy.call_args.args[0]
    assert normalized_payload["retrieval_evidence"] == evidence
    assert result["validation"]["retrieval_evidence"] == evidence


def test_run_validation_pipeline_rejects_invalid_retrieval_evidence(client):
    payload = {
        "context_id": "ctx-evidence",
        "policy_text": "policy",
        "structured_plan": {"sections": []},
        "retrieval_evidence": "not-a-list",
        "generated_at": "2026-03-05T00:00:00+00:00",
    }

    with client.application.test_request_context("/validate-policy", method="POST"):
        result = run_validation_pipeline(payload)

    assert result["success"] is False
    assert result["error_code"] == "invalid_field_type"
    assert result["details"]["field"] == "retrieval_evidence"


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


def test_run_validation_pipeline_rejects_non_object_json_body(client):
    with client.application.test_request_context("/validate-policy", method="POST"):
        result = run_validation_pipeline(["not", "an", "object"])

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "invalid_json_body",
        "message": "Request body must be a JSON object.",
        "details": {
            "stage": "contract_validation",
            "expected_type": "object",
        },
        "status_code": 400,
    }


def test_run_validation_pipeline_rejects_invalid_field_types(client):
    payload = {
        "context_id": "ctx-1",
        "policy_text": "policy",
        "structured_plan": {"sections": []},
        "generated_at": "2026-03-05T00:00:00+00:00",
        "language": ["en"],
    }

    with client.application.test_request_context("/validate-policy", method="POST"):
        result = run_validation_pipeline(payload)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "invalid_field_type",
        "message": "Field 'language' must be a string.",
        "details": {
            "stage": "contract_validation",
            "field": "language",
            "expected_type": "string",
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
