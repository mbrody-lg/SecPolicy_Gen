"""Service helpers for context prompting and policy pipeline orchestration."""

from datetime import datetime, timezone
import logging

import requests
import yaml
from bson import ObjectId
from flask import current_app
from markdown import markdown

from app import mongo
from app.agents.factory import create_agent_from_config

logger = logging.getLogger(__name__)


class PipelineStepError(Exception):
    """Structured pipeline error used to keep orchestration failures explicit."""

    def __init__(
        self,
        *,
        stage: str,
        message: str,
        error_type: str,
        error_code: str,
        status_code: int,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.error_type = error_type
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


def load_questions(config_path="app/config/context_questions.yaml"):
    """Load context-question definitions from YAML configuration."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]


def generate_context_prompt(data: dict, question_config="app/config/context_questions.yaml") -> str:
    """
    Build a text prompt from form answers.
    This prompt is used to drive context generation.
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


def run_with_agent(prompt: str, context_id: str = None, model_version: str = None) -> str:
    """
    Execute the configured agent using the initial prompt.
    The context_id can be used for session naming, assistant_id, or traceability.
    """
    config_path = "app/config/context_agent.yaml"
    _ = model_version
    agent = create_agent_from_config(config_path)
    agent.create(context_id=context_id)  # pass context_id when persistence is needed
    return agent.run(prompt, context_id)


def _result_error(error: str, details: str = "", status_code: int = 500) -> dict:
    return {"success": False, "error": error, "details": details, "status_code": status_code}


def _pipeline_success(*, stage: str, **payload) -> dict:
    result = {"success": True, "stage": stage}
    result.update(payload)
    return result


def _pipeline_error(exc: PipelineStepError) -> dict:
    return {
        "success": False,
        "stage": exc.stage,
        "error_type": exc.error_type,
        "error_code": exc.error_code,
        "message": exc.message,
        "details": exc.details,
        "status_code": exc.status_code,
    }


def get_context_and_prompt(context_id: str) -> dict:
    """Fetch context data and the refined prompt required by policy-agent."""
    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise PipelineStepError(
            stage="context_fetch",
            message="Invalid context_id format.",
            error_type="contract_error",
            error_code="invalid_context_id",
            status_code=400,
            details={"context_id": context_id},
        ) from exc

    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        raise PipelineStepError(
            stage="context_fetch",
            message="Context not found.",
            error_type="validation_error",
            error_code="context_not_found",
            status_code=404,
            details={"context_id": context_id},
        )

    refined_prompt = (context.get("refined_prompt") or "").strip()
    if not refined_prompt:
        prompt_entry = mongo.db.interactions.find_one(
            {"context_id": context_obj_id, "question_id": "refined_prompt"}
        )
        if not prompt_entry:
            if "refined_prompt" in context:
                raise PipelineStepError(
                    stage="context_fetch",
                    message="Refined prompt is empty.",
                    error_type="validation_error",
                    error_code="empty_refined_prompt",
                    status_code=400,
                    details={"context_id": context_id},
                )
            raise PipelineStepError(
                stage="context_fetch",
                message="Refined prompt not found.",
                error_type="validation_error",
                error_code="refined_prompt_not_found",
                status_code=404,
                details={"context_id": context_id},
            )

        refined_prompt = prompt_entry.get("answer", "").strip()
        if not refined_prompt:
            raise PipelineStepError(
                stage="context_fetch",
                message="Refined prompt is empty.",
                error_type="validation_error",
                error_code="empty_refined_prompt",
                status_code=400,
                details={"context_id": context_id},
            )

    return {
        "context_id": context_id,
        "refined_prompt": refined_prompt,
        "language": context.get("language", "en"),
        "model_version": context.get("version", "0.1.0"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def call_policy_agent(context_payload: dict) -> dict:
    """Call policy-agent and return parsed JSON response."""
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    try:
        response = requests.post(f"{policy_agent_url}/generate_policy", json=context_payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.warning(
            "Policy-agent request failed for context_id=%s",
            context_payload.get("context_id"),
            exc_info=exc,
        )
        raise PipelineStepError(
            stage="policy_generation",
            message="Policy generation failed.",
            error_type="dependency_error",
            error_code="policy_agent_request_failed",
            status_code=502,
            details={"target_service": "policy-agent"},
        ) from exc


def trigger_policy_generation(context_id: str) -> dict:
    """Generate policy data from stored context and refined prompt."""
    try:
        payload = get_context_and_prompt(context_id)
        policy_data = call_policy_agent(payload)
        return _pipeline_success(stage="policy_generation", policy_data=policy_data)
    except PipelineStepError as exc:
        return _pipeline_error(exc)
    except Exception as exc:  # unexpected errors
        logger.exception("Unexpected policy generation failure for context_id=%s", context_id)
        return _pipeline_error(
            PipelineStepError(
                stage="policy_generation",
                message="Policy generation failed.",
                error_type="internal_error",
                error_code="policy_generation_unexpected_failure",
                status_code=500,
                details={"operation": "trigger_policy_generation"},
            )
        )


def call_validator_agent(policy_data: dict) -> dict:
    """Call validator-agent and return parsed JSON response."""
    validator_agent_url = current_app.config.get("VALIDATOR_AGENT_URL", "http://validator-agent:5000")
    try:
        response = requests.post(f"{validator_agent_url}/validate-policy", json=policy_data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.warning(
            "Validator-agent request failed for context_id=%s",
            policy_data.get("context_id"),
            exc_info=exc,
        )
        raise PipelineStepError(
            stage="validation",
            message="Policy validation failed.",
            error_type="dependency_error",
            error_code="validator_agent_request_failed",
            status_code=502,
            details={"target_service": "validator-agent"},
        ) from exc


def store_validated_policy(context_id: str, validated_data: dict) -> dict:
    """Persist a validated policy payload in context interactions."""
    data = validated_data or {}
    required_fields = ["policy_text", "generated_at", "policy_agent_version", "language"]
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise PipelineStepError(
            stage="persistence",
            message="Validated policy payload is incomplete.",
            error_type="contract_error",
            error_code="validated_policy_missing_fields",
            status_code=400,
            details={"missing_fields": missing, "context_id": context_id},
        )

    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise PipelineStepError(
            stage="persistence",
            message="Invalid context_id format.",
            error_type="contract_error",
            error_code="invalid_context_id",
            status_code=400,
            details={"context_id": context_id},
        ) from exc

    validated_at = datetime.now(timezone.utc)
    mongo.db.interactions.insert_one({
        "context_id": context_obj_id,
        "question_id": "validated_policy",
        "question_text": "Agent-generated policy",
        "answer": data["policy_text"],
        "timestamp": validated_at,
        "origin": "agent",
        "status": data.get("status", "review"),
        "recommendations": data.get("recommendations", []),
        "generated_at": data["generated_at"],
        "policy_agent_version": data["policy_agent_version"],
        "language": data["language"],
        "ownership": {
            "owner_service": "context-agent",
            "source_of_truth": False,
            "view_type": "derived_policy_snapshot",
        },
        "policy_ref": {
            "owner_service": "policy-agent",
            "source_collection": "policies",
            "context_id": context_id,
        },
        "validation_ref": {
            "owner_service": "validator-agent",
            "source_collection": "validations",
            "context_id": context_id,
        },
    })
    return _pipeline_success(
        stage="persistence",
        context_id=context_id,
        stored_at=validated_at.isoformat(),
    )


def generate_full_policy_pipeline(context_id: str) -> dict:
    """Execute policy generation, validation, and context persistence pipeline."""
    try:
        policy_result = trigger_policy_generation(context_id)
        if not policy_result.get("success"):
            return policy_result

        policy_data = policy_result["policy_data"]
        validated_data = call_validator_agent(policy_data)
        persistence_result = store_validated_policy(context_id, validated_data)
        return _pipeline_success(
            stage="completed",
            validated_data=validated_data,
            persistence=persistence_result,
        )
    except PipelineStepError as exc:
        return _pipeline_error(exc)
    except Exception:
        logger.exception("Unexpected pipeline failure for context_id=%s", context_id)
        return _pipeline_error(
            PipelineStepError(
                stage="pipeline",
                message="Policy pipeline failed.",
                error_type="internal_error",
                error_code="policy_pipeline_unexpected_failure",
                status_code=500,
                details={"context_id": context_id},
            )
        )


def render_markdown(text):
    """Render markdown text as HTML for context-detail display."""
    return markdown(text or "", extensions=["fenced_code", "tables", "nl2br"])
