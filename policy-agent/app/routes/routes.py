"""HTTP routes for policy generation and policy revision workflow."""

from datetime import datetime, timezone
import json
import traceback

from bson import ObjectId
from flask import Blueprint, request, jsonify, abort

from app import mongo
from app.services.logic import run_with_agent, update_with_agent


routes = Blueprint("routes", __name__)

@routes.route("/generate_policy", methods=["POST"])
def generate_policy():
    """Generate a policy from refined context data via policy-agent pipeline."""
    data = request.get_json()
    required_fields = ["context_id", "refined_prompt", "language", "model_version"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Required fields are missing."}), 400

    try:
        result_object = run_with_agent(
            refined_prompt=data["refined_prompt"],
            context_id=data["context_id"],
            model_version=data["model_version"]
        )

        result = {
            "context_id": data["context_id"],
            "language": data["language"],
            "policy_text": result_object["text"],
            "structured_plan": result_object.get("structured_plan",[]),
            "model_version": data["model_version"],
            "policy_agent_version": "0.1.0",
            "generated_at":  datetime.now(timezone.utc)
        }

        mongo.db.policies.insert_one(result)
        return jsonify(result), 200

    except Exception as e:
        print("EXCEPTION:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@routes.route("/generate_policy/<context_id>/update", methods=["POST"])
def update_policy(context_id):
    """Regenerate policy text after validator feedback for a context."""
    data = request.get_json()
    required_fields = ["context_id", "language", "policy_text", "policy_agent_version", "generated_at", "status", "reasons", "recommendations"]

    context = None
    if str(data.get("context_id")) == str(context_id):
        context = mongo.db.contexts.find_one({"context_id": ObjectId(context_id)})
    if not context:
        return abort(404, "Context not found.")
    
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Required fields are missing."}), 400
    
    context_id = data.get("context_id")
    policy_text = data.get("policy_text")
    reasons = data.get("reasons", [])
    recommendations = data.get("recommendations", [])
    language = data.get("language", "")
    version = data.get("policy_agent_version", "")
    
    # Build prompt for IMQ role ("Incremental Model Query")
    prompt = (
        f"[Original Policy]:\n{policy_text}\n\n"
        f"[Reasons]:\n{json.dumps(reasons, indent=2)}\n\n"
        f"[Recommendations]:\n{json.dumps(recommendations, indent=2)}"
    )

    try:
        result_object = update_with_agent(
            prompt=prompt,
            context_id=data.get("context_id"),
            model_version=context.get("model_version")
        )

        result = {
            "context_id": data["context_id"],
            "language": language,
            "policy_text": result_object["text"],
            "structured_plan": context.get("structured_plan",[]),
            "model_version": context.get("model_version"),
            "policy_agent_version": version,
            "generated_at":  datetime.now(timezone.utc)
        }

        # Update stored document with refreshed prompt output
        # TODO: store all iterations for traceability.
        mongo.db.contexts.update_one(
            {"context_id": ObjectId(context_id)},
            {"$set": {
                "language": result["language"],
                "policy_text": result["policy_text"],
                "structured_plan": result["structured_plan"],
                "model_version": result["model_version"],
                "policy_agent_version": version,
                "generated_at": result["generated_at"]
            }}
        )

        return jsonify(result), 200

    except Exception as e:
        print("EXCEPTION:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
