"""Service helpers for policy-update communication with policy-agent."""

import os

import requests


POLICY_UPDATE_REQUIRED_FIELDS = [
    "context_id",
    "language",
    "policy_text",
    "policy_agent_version",
    "generated_at",
    "status",
    "reasons",
    "recommendations",
]


def _error_payload(
    *,
    error_type: str,
    error_code: str,
    message: str,
    details: dict | None = None,
    correlation_id: str | None = None,
) -> dict:
    body = {
        "success": False,
        "error_type": error_type,
        "error_code": error_code,
        "message": message,
        "details": details or {},
    }
    if correlation_id:
        body["correlation_id"] = correlation_id
    return body


def send_policy_update_to_policy_agent(
    context_id: str,
    language: str,
    policy_text: str,
    policy_agent_version: str,
    generated_at: str,
    status: str,
    reasons: list,
    recommendations: list,
):
    """Send validator feedback to policy-agent and return the revised policy payload."""
    policy_agent_url = os.getenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    update_endpoint = f"{policy_agent_url}/generate_policy/{context_id}/update"

    payload = {
        "context_id": context_id,
        "language": language,
        "policy_text": policy_text,
        "policy_agent_version": policy_agent_version,
        "generated_at": generated_at,
        "status": status,
        "reasons": reasons,
        "recommendations": recommendations,
    }

    try:
        response = requests.post(update_endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        return _error_payload(
            error_type="dependency_error",
            error_code="policy_update_request_failed",
            message="Error sending policy update to policy-agent.",
            details={
                "target_service": "policy-agent",
                "operation": "generate_policy_update",
                "exception": str(exc),
                "request_fields": POLICY_UPDATE_REQUIRED_FIELDS,
            },
            correlation_id=context_id,
        )
