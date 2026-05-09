from datetime import datetime, timezone
from unittest.mock import patch


class FakeCoordinator:
    def validate_policy(self, payload):
        return {
            "context_id": payload["context_id"],
            "language": payload.get("language", "en"),
            "policy_text": payload["policy_text"],
            "structured_plan": payload["structured_plan"],
            "retrieval_evidence": payload["retrieval_evidence"],
            "generated_at": payload["generated_at"],
            "policy_agent_version": payload.get("policy_agent_version", "0.1.0"),
            "status": "accepted",
            "reasons": [],
            "recommendations": [],
        }


def test_validate_policy_route(client):
    payload = {
        "context_id": "6648748a7b3d2a2c77e1fc04",
        "language": "en",
        "policy_text": "This policy establishes the principles for asset management...",
        "structured_plan" : [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_agent_version": "0.1.0"
    }

    with patch("app.services.logic.Coordinator", return_value=FakeCoordinator()):
        response = client.post("/validate-policy", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "accepted"
