"""HTTP routes for validator-agent validation and trace retrieval."""

from bson import ObjectId
from flask import Blueprint, abort, current_app, jsonify, request

from app import mongo
from app.agents.roles.coordinator import Coordinator

routes = Blueprint("routes", __name__)

VALIDATION_REQUIRED_FIELDS = ["context_id", "policy_text", "structured_plan", "generated_at"]


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


@routes.route("/validate-policy", methods=["POST"])
def validate_policy():
    """Validate policy payload received from policy-agent and return decision data."""
    data = request.get_json(silent=True) or {}
    missing = [field for field in VALIDATION_REQUIRED_FIELDS if field not in data]

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
        coordinator = Coordinator()
        validation_result = coordinator.validate_policy(data)

        if not validation_result.get("success", True):
            return jsonify(validation_result), 502

        response = {
            "success": True,
            "context_id": data["context_id"],
            "language": validation_result.get("language", data.get("language", "")),
            "policy_text": validation_result.get("policy_text", data["policy_text"]),
            "structured_plan": data["structured_plan"],
            "generated_at": validation_result.get("generated_at", data["generated_at"]),
            "policy_agent_version": validation_result.get(
                "policy_agent_version",
                data.get("policy_agent_version", ""),
            ),
            "status": validation_result.get("status", "review"),
            "reasons": validation_result.get("reasons", []),
            "recommendations": validation_result.get("recommendations", []),
        }

        if "evaluator_analysis" in validation_result:
            response["evaluator_analysis"] = validation_result["evaluator_analysis"]

        return jsonify(response), 200

    except Exception as exc:
        return _error_response(
            500,
            error_type="internal_error",
            error_code="validation_execution_failed",
            message="Validator execution failed.",
            details={"exception": str(exc)},
            payload=data,
        )


@routes.route("/validation/<context_id>", methods=["GET"])
def get_validations_by_context(context_id):
    """Return stored validation rounds for a given context identifier."""
    try:
        ObjectId(context_id)
    except Exception:
        return _error_response(
            400,
            error_type="contract_error",
            error_code="invalid_context_id",
            message="Invalid context_id format.",
            details={"context_id": context_id},
            payload={"context_id": context_id},
        )

    validations = list(mongo.db.validations.find({"context_id": context_id}).sort("round", 1))

    if not validations:
        return jsonify({"message": "No validation records found for this context."}), 404

    # Serialize ObjectId and timestamps for JSON response
    for v in validations:
        v["_id"] = str(v["_id"])
        v["context_id"] = str(v["context_id"])
        if "timestamp" in v:
            v["timestamp"] = v["timestamp"].isoformat()

    return jsonify(validations), 200

@routes.route("/validation/<context_id>", methods=["DELETE"])
def delete_validations_by_context(context_id):
    """Delete validation records for a context when test mode is enabled."""
    if not current_app.config.get("TESTING", False):
        abort(403, "This operation is only allowed in DEBUG mode.")

    try:
        ObjectId(context_id)
    except Exception:
        return _error_response(
            400,
            error_type="contract_error",
            error_code="invalid_context_id",
            message="Invalid context_id format.",
            details={"context_id": context_id},
            payload={"context_id": context_id},
        )

    result = mongo.db.validations.delete_many({"context_id": context_id})

    if result.deleted_count == 0:
        return jsonify({"message": "No validation records found for this context."}), 404

    return jsonify({
        "message": f"{result.deleted_count} validation(s) deleted for context_id: {context_id}"
    }), 200
