from datetime import datetime, timezone

import requests
import yaml
from bson import ObjectId
from flask import current_app
from markdown import markdown

from app import mongo
from app.agents.factory import create_agent_from_config

def load_questions(config_path="app/config/context_questions.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]

def generate_context_prompt(data: dict, question_config="app/config/context_questions.yaml") -> str:
    """
    Construeix un prompt textual a partir de les respostes del formulari.
    Aquest prompt serà utilitzat per alimentar un agent de generació.
    """
    questions = load_questions(question_config)

    lines = ["This is the context obtained from the questions asked:"]
    for q in questions:
        key = q["id"]
        answer = data.get(key, "").strip()
        if answer:
            lines.append(f"- {q['question']} {answer}")
    lines.append(
        "This context will be used by other agents to generate policies, security frameworks or specific validations."
    )
    return "\n".join(lines)

def run_with_agent(prompt: str, context_id: str = None, _model_version: str = None) -> str:
    """
    Executa l’agent configurat a partir del prompt inicial.
    El context_id es pot fer servir com a base per nom de sessió, assistant_id o traçabilitat.
    """
    config_path = "app/config/context_agent.yaml"
    agent = create_agent_from_config(config_path)
    agent.create(context_id=context_id)  # passem context_id si cal persistència
    return agent.run(prompt, context_id)


def get_context_and_prompt(context_id: str) -> dict:
    context = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
    if not context or "response" not in context:
        raise ValueError(f"The context was not found or the refined prompt is missing. {context}")
    return {
        "refined_prompt": context["response"],
        "language": context.get("language", "en"),
        "model_version": context.get("version", "0.1.0"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context_id": str(context["_id"]),
    }

def call_policy_agent(context_payload: dict) -> dict:
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    response = requests.post(f"{policy_agent_url}/generate_policy", json=context_payload)
    if response.status_code != 200:
        raise RuntimeError("Error generating policy", response.text)
    return response.json()

def trigger_policy_generation(context_id: str) -> dict:
    context_payload = get_context_and_prompt(context_id)
    return call_policy_agent(context_payload)

def call_validator_agent(policy_data: dict) -> dict:
    validator_agent_url = current_app.config.get("VALIDATOR_AGENT_URL", "http://validator-agent:5000")
    response = requests.post(f"{validator_agent_url}/validate-policy", json=policy_data)
    if response.status_code != 200:
        raise RuntimeError("Error validating policy", response.text)
    return response.json()

def forward_validated_policy(context_id: str, validated_data: dict):
    internal_context_url = f"http://localhost:5000/context/{context_id}/policy"
    response = requests.post(internal_context_url, json=validated_data)
    if response.status_code not in (200, 302):
        raise RuntimeError("Error saving validated policy", response.text)

def generate_full_policy_pipeline(context_id: str) -> dict:
    try:
        policy_data = trigger_policy_generation(context_id)
        validated_data = call_validator_agent(policy_data)
        forward_validated_policy(context_id, validated_data)
        return {"success": True, "validated_data": validated_data}
    except Exception as e:
        return {"error": str(e), "details": getattr(e, "args", ["Sense detalls"])[-1]}

def render_markdown(text):
    return markdown(text or "", extensions=["fenced_code", "tables", "nl2br"])
