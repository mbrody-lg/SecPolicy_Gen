"""HTTP routes for policy generation and policy revision workflow."""

from datetime import datetime, timezone
import json

from flask import Blueprint, jsonify, request

from app import mongo
from app.services.logic import run_with_agent, update_with_agent


routes = Blueprint("routes", __name__)

POLICY_GENERATION_REQUIRED_FIELDS = ["context_id", "refined_prompt", "language", "model_version"]
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


def _get_correlation_id(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return request.headers.get("X-Correlation-ID")
    return (
        request.headers.get("X-Correlation-ID")
        or payload.get("correlation_id")
        or payload.get("context_id")
    )


def _error_payload(
    *,
    error_type: str,
    error_code: str,
    message: str,
    details: dict | None = None,
    payload: dict | None = None,
) -> dict:
    body = {
        "success": False,
        "error_type": error_type,
        "error_code": error_code,
        "message": message,
        "details": details or {},
    }
    correlation_id = _get_correlation_id(payload)
    if correlation_id:
        body["correlation_id"] = correlation_id
    return body


def _error_response(status_code: int, **kwargs):
    return jsonify(_error_payload(**kwargs)), status_code


def _missing_fields(payload: dict, required_fields: list[str]) -> list[str]:
    return [field for field in required_fields if field not in payload]


@routes.route("/generate_policy", methods=["POST"])
def generate_policy():
    """Generate a policy from refined context data via policy-agent pipeline."""
    data = request.get_json(silent=True) or {}
    missing = _missing_fields(data, POLICY_GENERATION_REQUIRED_FIELDS)
    if missing:
        return _error_response(
            400,
            error_type="contract_error",
            error_code="missing_required_fields",
            message="Required fields are missing.",
            details={"missing_fields": missing},
            payload=data,
        )

    try:
        result_object = run_with_agent(
            refined_prompt=data["refined_prompt"],
            context_id=data["context_id"],
            model_version=data["model_version"],
        )

        result = {
            "success": True,
            "context_id": data["context_id"],
            "language": data["language"],
            "policy_text": result_object["text"],
            "structured_plan": result_object.get("structured_plan", []),
            "model_version": data["model_version"],
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        mongo.db.policies.insert_one(result)
        return jsonify(result), 200

    except Exception as exc:
        return _error_response(
            500,
            error_type="internal_error",
            error_code="policy_generation_failed",
            message="Policy generation failed.",
            details={"exception": str(exc)},
            payload=data,
        )


@routes.route("/generate_policy/<context_id>/update", methods=["POST"])
def update_policy(context_id):
    """Regenerate policy text after validator feedback for a context."""
    data = request.get_json(silent=True) or {}
    missing = _missing_fields(data, POLICY_UPDATE_REQUIRED_FIELDS)
    if missing:
        return _error_response(
            400,
            error_type="contract_error",
            error_code="missing_required_fields",
            message="Required fields are missing.",
            details={"missing_fields": missing},
            payload=data,
        )

    if str(data.get("context_id")) != str(context_id):
        return _error_response(
            400,
            error_type="contract_error",
            error_code="context_id_mismatch",
            message="Context ID mismatch.",
            details={
                "path_context_id": str(context_id),
                "payload_context_id": str(data.get("context_id")),
            },
            payload=data,
        )

    policy = mongo.db.policies.find_one({"context_id": str(context_id)})
    if not policy:
        return _error_response(
            404,
            error_type="validation_error",
            error_code="policy_not_found",
            message="Policy not found.",
            details={"context_id": str(context_id)},
            payload=data,
        )

    policy_text = data.get("policy_text")
    reasons = data.get("reasons", [])
    recommendations = data.get("recommendations", [])
    language = data.get("language", "")
    version = data.get("policy_agent_version", "")

    prompt = (
        f"[Original Policy]:\n{policy_text}\n\n"
        f"[Reasons]:\n{json.dumps(reasons, indent=2)}\n\n"
        f"[Recommendations]:\n{json.dumps(recommendations, indent=2)}"
    )

    try:
        result_object = update_with_agent(
            prompt=prompt,
            context_id=str(context_id),
            model_version=policy.get("model_version"),
        )

        result = {
            "success": True,
            "context_id": data["context_id"],
            "language": language,
            "policy_text": result_object["text"],
            "structured_plan": policy.get("structured_plan", []),
            "model_version": policy.get("model_version"),
            "policy_agent_version": version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        mongo.db.policies.update_one(
            {"_id": policy["_id"]},
            {"$set": {
                "language": result["language"],
                "policy_text": result["policy_text"],
                "structured_plan": result["structured_plan"],
                "model_version": result["model_version"],
                "policy_agent_version": version,
                "generated_at": result["generated_at"],
            }},
        )

        return jsonify(result), 200

    except Exception as exc:
        return _error_response(
            500,
            error_type="internal_error",
            error_code="policy_update_failed",
            message="Policy update failed.",
            details={"exception": str(exc)},
            payload=data,
        )
