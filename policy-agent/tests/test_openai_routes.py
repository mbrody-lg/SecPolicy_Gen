import json
from unittest.mock import patch

import pytest
from flask import g
from app.routes import routes as routes_module

pytestmark = [pytest.mark.route]


def test_health_route_returns_lightweight_service_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "policy-agent",
    }


def test_ready_route_reports_success(client):
    with patch(
        "app.routes.routes.get_readiness_status",
        return_value=(
            {
                "status": "ready",
                "service": "policy-agent",
                "checks": {
                    "config": {"status": "ok", "source": "loaded"},
                    "mongo": {"status": "ok"},
                    "chroma": {"status": "configured", "mode": "config_only"},
                },
            },
            200,
        ),
    ):
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert response.get_json()["checks"]["mongo"] == {"status": "ok"}


def test_ready_route_reports_controlled_failure(client):
    with patch(
        "app.routes.routes.get_readiness_status",
        return_value=(
            {
                "status": "not_ready",
                "service": "policy-agent",
                "checks": {
                    "config": {"status": "ok", "source": "loaded"},
                    "mongo": {
                        "status": "error",
                        "reason": "ping_failed",
                    },
                    "chroma": {"status": "configured", "mode": "config_only"},
                },
            },
            503,
        ),
    ):
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.get_json()["status"] == "not_ready"
    assert response.get_json()["checks"]["mongo"]["reason"] == "ping_failed"
    assert "details" not in response.get_json()["checks"]["mongo"]


def test_generate_policy_route_rejects_missing_required_fields(client):
    with patch(
        "app.routes.routes.run_generation_pipeline",
        return_value={
            "success": False,
            "error_type": "contract_error",
            "error_code": "missing_required_fields",
            "message": "Required fields are missing.",
            "details": {"stage": "contract_validation", "missing_fields": ["language", "model_version"]},
            "correlation_id": "ctx-1",
            "status_code": 400,
        },
    ):
        response = client.post(
            "/generate_policy",
            data=json.dumps({"context_id": "ctx-1", "refined_prompt": "prompt only"}),
            content_type="application/json",
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "missing_required_fields",
        "message": "Required fields are missing.",
        "details": {
            "stage": "contract_validation",
            "missing_fields": ["language", "model_version"],
        },
        "correlation_id": "ctx-1",
    }


def test_generate_policy_route_with_openai(
    client,
    default_prompt,
    default_context_id,
    openai_model_version,
    default_language,
    monkeypatch,
):
    monkeypatch.setattr(
        routes_module,
        "run_generation_pipeline",
        lambda payload: {
            "success": True,
            "stage": "completed",
            "policy": {
                "success": True,
                "context_id": payload["context_id"],
                "language": payload["language"],
                "policy_text": "[Generated policy simulation] Access control and incident response policy",
                "structured_plan": ["scope", "controls"],
                "model_version": payload["model_version"],
                "policy_agent_version": "0.1.0",
                "generated_at": "2026-04-22T00:00:00+00:00",
                "lifecycle_status": "generated",
                "revision_count": 0,
                "ownership": {
                    "owner_service": "policy-agent",
                    "source_of_truth": True,
                    "collection": "policies",
                },
            },
        },
    )
    payload = {
        "context_id": default_context_id,
        "refined_prompt": default_prompt,
        "language": default_language,
        "model_version": openai_model_version,
    }

    with patch(
        "app.routes.routes.run_generation_pipeline",
        return_value={
            "success": True,
            "stage": "completed",
            "policy": {
                "success": True,
                "context_id": payload["context_id"],
                "language": payload["language"],
                "policy_text": "[Generated policy simulation] Policy body",
                "structured_plan": [{"id": "proposal_1", "content": "Plan"}],
                "model_version": payload["model_version"],
                "policy_agent_version": "0.1.0",
                "generated_at": "2026-04-22T00:00:00+00:00",
                "lifecycle_status": "generated",
                "revision_count": 0,
                "ownership": {
                    "owner_service": "policy-agent",
                    "source_of_truth": True,
                    "collection": "policies",
                },
            },
        },
    ):
        response = client.post(
            "/generate_policy",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = response.get_json()

    assert "policy_text" in data
    assert "context_id" in data
    assert "model_version" in data
    assert "structured_plan" in data
    assert "language" in data
    assert data["context_id"] == payload["context_id"]
    assert data["language"] == payload["language"]
    assert "[Generated policy simulation]" in data["policy_text"]
    assert data["ownership"] == {
        "owner_service": "policy-agent",
        "source_of_truth": True,
        "collection": "policies",
    }
    assert data["lifecycle_status"] == "generated"
    assert data["revision_count"] == 0


def test_generate_policy_route_returns_deterministic_internal_error(client):
    payload = {
        "context_id": "ctx-err",
        "refined_prompt": "Generate a policy",
        "language": "en",
        "model_version": "gpt-4",
    }

    with patch(
        "app.routes.routes.run_generation_pipeline",
        return_value={
            "success": False,
            "error_type": "internal_error",
            "error_code": "policy_generation_failed",
            "message": "Policy generation failed.",
            "details": {"stage": "policy_generation", "operation": "generate_policy"},
            "correlation_id": "ctx-err",
            "status_code": 500,
        },
    ):
        response = client.post(
            "/generate_policy",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "error_type": "internal_error",
        "error_code": "policy_generation_failed",
        "message": "Policy generation failed.",
        "details": {"stage": "policy_generation", "operation": "generate_policy"},
        "correlation_id": "ctx-err",
    }


def test_generate_policy_route_adds_security_headers(client):
    with patch(
        "app.routes.routes.run_generation_pipeline",
        return_value={
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_json_body",
            "message": "Request body must be a JSON object.",
            "details": {"stage": "contract_validation", "expected_type": "object"},
            "status_code": 400,
        },
    ):
        response = client.post(
            "/generate_policy",
            data="[]",
            content_type="application/json",
        )

    assert response.status_code == 400
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_generate_policy_route_preserves_request_correlation_id(client):
    captured = {}

    def fake_run_generation_pipeline(payload):
        captured["correlation_id"] = g.correlation_id
        return {
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_json_body",
            "message": "Request body must be a JSON object.",
            "details": {"stage": "contract_validation", "expected_type": "object"},
            "status_code": 400,
        }

    with patch("app.routes.routes.run_generation_pipeline", side_effect=fake_run_generation_pipeline):
        response = client.post(
            "/generate_policy",
            data="[]",
            content_type="application/json",
            headers={"X-Correlation-ID": "request-correlation-id"},
        )

    assert captured["correlation_id"] == "request-correlation-id"
    assert response.headers["X-Correlation-ID"] == "request-correlation-id"
    assert response.get_json()["correlation_id"] == "request-correlation-id"


def test_generate_policy_route_generates_request_correlation_id_when_missing(client):
    captured = {}

    def fake_run_generation_pipeline(payload):
        captured["correlation_id"] = g.correlation_id
        return {
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_json_body",
            "message": "Request body must be a JSON object.",
            "details": {"stage": "contract_validation", "expected_type": "object"},
            "status_code": 400,
        }

    with patch("app.routes.routes.run_generation_pipeline", side_effect=fake_run_generation_pipeline):
        response = client.post(
            "/generate_policy",
            data="[]",
            content_type="application/json",
        )

    correlation_id = response.headers["X-Correlation-ID"]
    assert correlation_id
    assert captured["correlation_id"] == correlation_id
    assert response.get_json()["correlation_id"] == correlation_id
