import os
import requests
from datetime import datetime

def send_policy_update_to_policy_agent(context_id: str, updated_text: str, reason: str, recommendations: list, version: str = "v1.0", language: str = "en"):
    """
    Envia la resposta validada cap al policy-agent per fer update de la política.
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
            "message": "Policy update enviada correctament.",
            "response": response.json()
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Error enviant l'actualització al policy-agent: {str(e)}"
        }
