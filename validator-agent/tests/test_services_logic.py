from unittest.mock import MagicMock, patch

import requests

from app.services.logic import send_policy_update_to_policy_agent


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
            "exception": "boom",
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
