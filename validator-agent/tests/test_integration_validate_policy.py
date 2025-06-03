from datetime import datetime, timezone

def test_validate_policy_route(client):
    payload = {
        "context_id": "6648748a7b3d2a2c77e1fc04",
        "language": "en",
        "policy_text": "This policy establishes the principles for asset management...",
        "structured_plan" : [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_agent_version": "0.1.0"
    }

    response = client.post("/validate-policy", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] in ["accepted", "review", "rejected"]
