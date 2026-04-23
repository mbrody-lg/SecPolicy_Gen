from datetime import datetime, timezone
from unittest.mock import patch

from bson import ObjectId

def test_update_policy_with_openaiagent(client):
    context_id = ObjectId()
    data = {
        "context_id": str(context_id),
        "language": "ca",
        "policy_text": (
            "This policy has been rejected because it does not define clear "
            "security measures or incident processes."
        ),
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "not_accepted",
        "reasons": [
            "Does not include access controls",
            "The incident management description is missing."
        ],
        "recommendations": [
            "Add multi-factor authentication",
            "Include an incident response plan"
        ]
    }

    with patch(
        "app.routes.routes.run_policy_update_pipeline",
        return_value={
            "success": True,
            "stage": "completed",
            "policy": {
                "success": True,
                "context_id": str(context_id),
                "language": "ca",
                "policy_text": "Updated policy with incident response and access controls.",
                "structured_plan": [],
                "model_version": "gpt-4",
                "policy_agent_version": "0.1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "lifecycle_status": "revised",
                "revision_count": 1,
                "ownership": {
                    "owner_service": "policy-agent",
                    "source_of_truth": True,
                    "collection": "policies",
                },
                "last_validation_status": "not_accepted",
                "last_validation_reasons": data["reasons"],
                "last_validation_recommendations": data["recommendations"],
            },
        },
    ) as run_policy_update_pipeline:
        response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 200
    json_data = response.get_json()
    run_policy_update_pipeline.assert_called_once()
    assert json_data["ownership"] == {
        "owner_service": "policy-agent",
        "source_of_truth": True,
        "collection": "policies",
    }
    assert json_data["lifecycle_status"] == "revised"
    assert json_data["revision_count"] == 1
    assert json_data["last_validation_status"] == "not_accepted"
    assert json_data["last_validation_reasons"] == data["reasons"]
    assert json_data["last_validation_recommendations"] == data["recommendations"]

    assert "incident" in json_data["policy_text"].lower() or "access" in json_data["policy_text"].lower()


def test_update_policy_returns_404_when_canonical_policy_is_missing(client):
    context_id = ObjectId()
    data = {
        "context_id": str(context_id),
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": ["reason"],
        "recommendations": ["recommendation"],
    }

    with patch(
        "app.routes.routes.run_policy_update_pipeline",
        return_value={
            "success": False,
            "error_type": "validation_error",
            "error_code": "policy_not_found",
            "message": "Policy not found.",
            "details": {"stage": "persistence_lookup", "context_id": str(context_id)},
            "correlation_id": str(context_id),
            "status_code": 404,
        },
    ):
        response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 404
    assert response.get_json() == {
        "success": False,
        "error_type": "validation_error",
        "error_code": "policy_not_found",
        "message": "Policy not found.",
        "details": {"stage": "persistence_lookup", "context_id": str(context_id)},
        "correlation_id": str(context_id),
    }


def test_update_policy_returns_contract_error_when_context_id_mismatches(client):
    context_id = ObjectId()
    data = {
        "context_id": str(ObjectId()),
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": ["reason"],
        "recommendations": ["recommendation"],
    }

    with patch(
        "app.routes.routes.run_policy_update_pipeline",
        return_value={
            "success": False,
            "error_type": "contract_error",
            "error_code": "context_id_mismatch",
            "message": "Context ID mismatch.",
            "details": {
                "stage": "contract_validation",
                "path_context_id": str(context_id),
                "payload_context_id": data["context_id"],
            },
            "correlation_id": data["context_id"],
            "status_code": 400,
        },
    ):
        response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "context_id_mismatch",
        "message": "Context ID mismatch.",
        "details": {
            "stage": "contract_validation",
            "path_context_id": str(context_id),
            "payload_context_id": data["context_id"],
        },
        "correlation_id": data["context_id"],
    }


def test_update_policy_hides_internal_exception_details(client):
    context_id = ObjectId()
    data = {
        "context_id": str(context_id),
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": ["reason"],
        "recommendations": ["recommendation"],
    }

    with patch(
        "app.routes.routes.run_policy_update_pipeline",
        return_value={
            "success": False,
            "error_type": "internal_error",
            "error_code": "policy_update_failed",
            "message": "Policy update failed.",
            "details": {"stage": "policy_update", "operation": "update_policy"},
            "correlation_id": str(context_id),
            "status_code": 500,
        },
    ):
        response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "error_type": "internal_error",
        "error_code": "policy_update_failed",
        "message": "Policy update failed.",
        "details": {"stage": "policy_update", "operation": "update_policy"},
        "correlation_id": str(context_id),
    }
