"""Service helpers for policy-update communication with policy-agent."""

import os

import requests


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

    final_policy_text = policy_text if policy_text is not None else updated_text
    resolved_reasons = _normalize_reasons(
        reasons if reasons is not None else reason
    )

    final_version = policy_agent_version or version
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
    payload = _serialize_for_json(payload)

    try:
        response = requests.post(update_endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        return {
            "success": False,
            "error": f"Error sending policy update to policy-agent: {exc}",
        }
