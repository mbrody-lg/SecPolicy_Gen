import pytest
from bson import ObjectId
from datetime import datetime, timezone
from app import mongo

def test_update_policy_with_openaiagent(client):
    # Inserim context fictici a Mongo (mongomock o real)
    context_id = ObjectId()
    mongo.db.contexts.insert_one({
        "context_id": context_id,
        "structured_plan": [],
        "model_version": "gpt-4"
    })
    print(f"test context_id: {context_id}");

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

    # Fem la petició POST real a la ruta
    response = client.post(f"/generate_policy/{context_id}/update", json=data)

    assert response.status_code == 200
    json_data = response.get_json()

    print("\n== REFINED POLICY (OpenAI) ==")
    print(json_data["policy_text"])
    assert "incident" in json_data["policy_text"].lower() or "access" in json_data["policy_text"].lower()
