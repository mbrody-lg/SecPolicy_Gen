import json
from datetime import datetime, timezone
from unittest.mock import patch

from bson import ObjectId

from app import mongo

import pytest

pytestmark = [pytest.mark.route]


def test_validate_policy_route_rejects_missing_required_fields(client):
    with patch(
        "app.routes.routes.run_validation_pipeline",
        return_value={
            "success": False,
            "error_type": "contract_error",
            "error_code": "missing_required_fields",
            "message": "Required fields are missing.",
            "details": {"stage": "contract_validation", "missing_fields": ["structured_plan", "generated_at"]},
            "correlation_id": "ctx-1",
            "status_code": 400,
        },
    ):
        response = client.post(
            "/validate-policy",
            data=json.dumps({"context_id": "ctx-1", "policy_text": "policy"}),
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
            "missing_fields": ["structured_plan", "generated_at"],
        },
        "correlation_id": "ctx-1",
    }


def test_validate_policy_route_rejects_invalid_json_body(client):
    response = client.post(
        "/validate-policy",
        data="[]",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "invalid_json_body",
        "message": "Request body must be a JSON object.",
        "details": {
            "stage": "contract_validation",
            "expected_type": "object",
        },
    }
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_validate_policy_route(client, default_context_id):
    payload = {
        "context_id": default_context_id,
        "policy_text": "This policy establishes the principles for asset management...",
        "structured_plan": "Structured simulated security plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "en",
        "policy_agent_version": "0.1.0"
    }

    validation_result = {
        "context_id": default_context_id,
        "language": "en",
        "policy_text": "revised policy text",
        "structured_plan": "Structured simulated security plan",
        "policy_agent_version": "0.2.0",
        "generated_at": "2026-03-05T01:00:00+00:00",
        "status": "review",
        "reasons": ["Missing controls"],
        "recommendations": ["Add controls"],
        "evaluator_analysis": {"status": "review"},
    }

    with patch(
        "app.routes.routes.run_validation_pipeline",
        return_value={"success": True, "stage": "completed", "validation": validation_result, "status_code": 200},
    ):
        response = client.post(
            "/validate-policy",
            data=json.dumps(payload),
            content_type="application/json"
        )

    assert response.status_code == 200

    data = response.get_json()

    assert data["context_id"] == default_context_id
    assert data["language"] == "en"
    assert data["policy_text"] == "revised policy text"
    assert data["generated_at"] == "2026-03-05T01:00:00+00:00"
    assert data["policy_agent_version"] == "0.2.0"
    assert data["structured_plan"] == "Structured simulated security plan"
    assert data["status"] == "review"
    assert data["reasons"] == ["Missing controls"]
    assert data["recommendations"] == ["Add controls"]
    assert data["evaluator_analysis"] == {"status": "review"}


def test_validate_policy_route_propagates_dependency_error(client):
    payload = {
        "context_id": "ctx-dep",
        "policy_text": "Policy text",
        "structured_plan": [],
        "generated_at": "2026-03-05T01:00:00+00:00",
    }
    dependency_error = {
        "success": False,
        "error_type": "dependency_error",
        "error_code": "policy_update_request_failed",
        "message": "Error sending policy update to policy-agent.",
        "details": {"target_service": "policy-agent"},
        "correlation_id": "ctx-dep",
    }

    with patch(
        "app.routes.routes.run_validation_pipeline",
        return_value={**dependency_error, "status_code": 502},
    ):
        response = client.post(
            "/validate-policy",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 502
    assert response.get_json() == dependency_error


def test_validate_policy_route_hides_internal_exception_details(client):
    payload = {
        "context_id": "ctx-int",
        "policy_text": "Policy text",
        "structured_plan": [],
        "generated_at": "2026-03-05T01:00:00+00:00",
    }
    with patch(
        "app.routes.routes.run_validation_pipeline",
        return_value={
            "success": False,
            "error_type": "internal_error",
            "error_code": "validation_execution_failed",
            "message": "Validator execution failed.",
            "details": {"stage": "validation", "operation": "validate_policy"},
            "correlation_id": "ctx-int",
            "status_code": 500,
        },
    ):
        response = client.post(
            "/validate-policy",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "error_type": "internal_error",
        "error_code": "validation_execution_failed",
        "message": "Validator execution failed.",
        "details": {"stage": "validation", "operation": "validate_policy"},
        "correlation_id": "ctx-int",
    }

def test_delete_validation_by_context(client, app_context):
    context_id = str(ObjectId())
    mongo.db.validations.insert_one({
        "context_id": context_id,
        "round": 1,
        "consensus_achieved": True,
        "final_decision": "accepted",
        "results": [],
        "config_used": {
            "rounds": 3,
            "threshold": 2,
            "strategy": "majority"
        }
    })
    response = client.delete(f"/validation/{context_id}")
    assert response.status_code == 200

    json_response = response.get_json()
    assert "deleted" in json_response.get("message", "").lower()

    remaining = list(mongo.db.validations.find({"context_id": context_id}))
    assert len(remaining) == 0
