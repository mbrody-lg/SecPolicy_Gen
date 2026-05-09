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
            "status": "review",
            "reasons": ["Needs additional evidence."],
            "recommendations": ["Add source traceability."],
        }


def test_validator_agent_all_roles(client, default_prompt, default_context_id):
    with patch("app.services.logic.Coordinator", return_value=FakeCoordinator()):
        response = client.post("/validate-policy", json={
            "context_id": default_context_id,
            "policy_text": default_prompt,
            "structured_plan": "Fake structure",
            "generated_at": "2025-05-21T12:00:00Z"
        })

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "review"
