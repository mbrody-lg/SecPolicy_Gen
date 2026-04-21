from datetime import datetime, timezone
from unittest.mock import patch

from bson import ObjectId

from app import mongo
from app.routes import routes as routes_module

def test_update_policy_with_openaiagent(client):
    context_id = ObjectId()
    mongo.db.policies.insert_one({
        "context_id": str(context_id),
        "language": "ca",
        "policy_text": "previous policy",
        "structured_plan": [],
        "model_version": "gpt-4",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc),
    })

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
        "app.routes.routes.update_with_agent",
        return_value={"text": "Updated policy with incident response and access controls."},
    ) as update_with_agent:
        response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 200
    json_data = response.get_json()
    stored_policy = mongo.db.policies.find_one({"context_id": str(context_id)})
    assert stored_policy is not None
    assert stored_policy["policy_text"] == json_data["policy_text"]
    assert mongo.db.contexts.find_one({"context_id": context_id}) is None
    update_with_agent.assert_called_once()

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

    response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 404
    assert response.get_json() == {
        "success": False,
        "error_type": "validation_error",
        "error_code": "policy_not_found",
        "message": "Policy not found.",
        "details": {"context_id": str(context_id)},
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

    response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "context_id_mismatch",
        "message": "Context ID mismatch.",
        "details": {
            "path_context_id": str(context_id),
            "payload_context_id": data["context_id"],
        },
        "correlation_id": data["context_id"],
    }
