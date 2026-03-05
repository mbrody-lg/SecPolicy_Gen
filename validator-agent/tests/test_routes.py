from flask import json
from bson import ObjectId
from app import mongo
from datetime import datetime, timezone
import json

def test_validate_policy_route(client, default_context_id):
    payload = {
        "context_id": default_context_id,
        "policy_text": "This policy establishes the principles for asset management...",
        "structured_plan": "Structured simulated security plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "en",
        "policy_agent_version": "0.1.0"
    }

    response = client.post(
        "/validate-policy",
        data=json.dumps(payload),
        content_type="application/json"
    )
    
    assert response.status_code == 200

    data = response.get_json()

    # Validate basic returned fields
    assert "context_id" in data
    assert data["context_id"] == default_context_id
    assert "language" in data
    assert "policy_text" in data
    assert "generated_at" in data
    assert "policy_agent_version" in data

    # Validate response has validation structure
    assert "status" in data

    # If status is not accepted, recommendations must exist
    if data["status"] != "accepted":
        assert "recommendations" in data
        assert "reasons" in data

    assert data["status"] in ["accepted", "review", "rejected"]

def test_delete_validation_by_context(client, app_context):
    # Insert mock validation record with context_id
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
    print(f"test context_id: {context_id}");

    # Execute DELETE request
    response = client.delete(f"/validation/{context_id}")
    assert response.status_code == 200

    json_response = response.get_json()
    assert "deleted" in json_response.get("message", "").lower()

    # Verify it was actually deleted
    remaining = list(mongo.db.validations.find({"context_id": context_id}))
    assert len(remaining) == 0
