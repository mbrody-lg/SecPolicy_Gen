"""Service helpers for policy-update communication with policy-agent."""

import os
from datetime import date, datetime
from typing import List, Optional

import requests

def _normalize_reasons(reason_or_list: Optional[object]) -> list:
    """Normalize reason payload to a list expected by policy-agent."""
    if reason_or_list is None:
        return []
    if isinstance(reason_or_list, list):
        return [item for item in reason_or_list if item]
    return [reason_or_list]


def _serialize_for_json(value: object):
    """Convert non-JSON-serializable values used by the pipeline."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_for_json(item) for key, item in value.items()}
    return value

def send_policy_update_to_policy_agent(
    context_id: str,
    updated_text: Optional[str] = None,
    reason: Optional[str] = None,
    recommendations: Optional[List[str]] = None,
    version: str = "0.1.0",
    language: str = "en",
    *,
    policy_text: Optional[str] = None,
    status: str = "review",
    reasons: Optional[object] = None,
    policy_agent_version: Optional[str] = None,
    generated_at: Optional[str] = None,
    **_extra_kwargs,
):
    """
    Send validated output to policy-agent to request policy revision.
    """
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
        "policy_text": final_policy_text,
        "policy_agent_version": final_version,
        "generated_at": generated_at if generated_at is not None else datetime.utcnow().isoformat(),
        "status": status,
        "reasons": resolved_reasons,
        "recommendations": recommendations,
    }
    payload = _serialize_for_json(payload)

    try:
        response = requests.post(update_endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Error sending policy update to policy-agent: {str(e)}"
        }
