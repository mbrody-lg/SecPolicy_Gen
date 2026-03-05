"""Service helpers for policy-update communication with policy-agent."""

import os
from datetime import datetime

import requests

def send_policy_update_to_policy_agent(context_id: str, updated_text: str, reason: str, recommendations: list, version: str = "v1.0", language: str = "en"):
    """
    Send validated output to policy-agent to request policy revision.
    """
    policy_agent_url = os.getenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    update_endpoint = f"{policy_agent_url}/generate_policy/{context_id}/update"

    payload = {
        "context_id": context_id,
        "language": language,
        "policy_text": updated_text,
        "policy_agent_version": version,
        "generated_at": datetime.utcnow().isoformat(),
        "status": "review",
        "reasons": [reason] if isinstance(reason, str) else reason,
        "recommendations": recommendations
    }

    try:
        response = requests.post(update_endpoint, json=payload)
        response.raise_for_status()
        return {
            "success": True,
            "message": "Policy update sent successfully.",
            "response": response.json()
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Error sending policy update to policy-agent: {str(e)}"
        }
