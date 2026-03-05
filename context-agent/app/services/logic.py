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


def _result_error(error: str, details: str = "", status_code: int = 500) -> dict:
    return {"success": False, "error": error, "details": details, "status_code": status_code}


def get_context_and_prompt(context_id: str) -> dict:
    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise ValueError("Invalid context_id format.") from exc

    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        raise LookupError("Context not found")

    prompt_entry = mongo.db.interactions.find_one(
        {"context_id": context_obj_id, "question_id": "refined_prompt"}
    )
    if not prompt_entry:
        raise LookupError("Refined prompt not found")

    refined_prompt = prompt_entry.get("answer", "").strip()
    if not refined_prompt:
        raise ValueError("Refined prompt is empty")

    return {
        "context_id": context_id,
        "refined_prompt": refined_prompt,
        "language": context.get("language", "ca"),
        "model_version": context.get("version", "0.1.0"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def call_policy_agent(context_payload: dict) -> dict:
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    response = requests.post(f"{policy_agent_url}/generate_policy", json=context_payload)
    if response.status_code != 200:
        raise RuntimeError("Error generating policy", response.text)
    return response.json()


def trigger_policy_generation(context_id: str) -> dict:
    try:
        payload = get_context_and_prompt(context_id)
        policy_data = call_policy_agent(payload)
        return {"success": True, "policy_data": policy_data}
    except ValueError as exc:
        return _result_error(str(exc), status_code=400)
    except LookupError as exc:
        return _result_error(str(exc), status_code=404)
    except Exception as exc:  # network/service errors
        details = getattr(exc, "args", [""])[-1]
        return _result_error("Error generating policy", str(details), status_code=500)


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
        policy_result = trigger_policy_generation(context_id)
        if not policy_result.get("success"):
            return policy_result

        policy_data = policy_result["policy_data"]
        validated_data = call_validator_agent(policy_data)
        forward_validated_policy(context_id, validated_data)
        return {"success": True, "validated_data": validated_data}
    except Exception as exc:
        details = getattr(exc, "args", [""])[-1]
        return _result_error("Policy generation failed.", str(details), status_code=500)


def render_markdown(text):
    return markdown(text or "", extensions=["fenced_code", "tables", "nl2br"])
