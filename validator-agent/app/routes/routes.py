"""HTTP routes for validator-agent validation and trace retrieval."""

import logging

from bson import ObjectId
from flask import Blueprint, abort, current_app, jsonify, request

from app import mongo
from app.services.logic import run_validation_pipeline

routes = Blueprint("routes", __name__)
logger = logging.getLogger(__name__)


@routes.route("/validate-policy", methods=["POST"])
def validate_policy():
    """Validate policy payload received from policy-agent and return decision data."""
    data = request.get_json(silent=True) or {}
    result = run_validation_pipeline(data)
    status_code = result.pop("status_code", 200)
    if result.get("success"):
        return jsonify(result["validation"]), status_code
    return jsonify(result), status_code


@routes.route("/validation/<context_id>", methods=["GET"])
def get_validations_by_context(context_id):
    """Return stored validation rounds for a given context identifier."""
    try:
        ObjectId(context_id)
    except Exception:
        return jsonify({
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_context_id",
            "message": "Invalid context_id format.",
            "details": {"context_id": context_id},
            "correlation_id": context_id,
        }), 400

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
        return jsonify({
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_context_id",
            "message": "Invalid context_id format.",
            "details": {"context_id": context_id},
            "correlation_id": context_id,
        }), 400

    result = mongo.db.validations.delete_many({"context_id": context_id})

    if result.deleted_count == 0:
        return jsonify({"message": "No validation records found for this context."}), 404

    return jsonify({
        "message": f"{result.deleted_count} validation(s) deleted for context_id: {context_id}"
    }), 200
