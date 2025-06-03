from flask import Blueprint, request, jsonify, abort
from app.services.logic import run_with_agent, update_with_agent
from app import mongo
from datetime import datetime, timezone
import json
from bson import ObjectId
import traceback


routes = Blueprint("routes", __name__)

@routes.route("/generate_policy", methods=["POST"])
def generate_policy():
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
    data = request.get_json()
    required_fields = ["context_id", "language", "policy_text", "policy_agent_version", "generated_at", "status", "reasons", "recommendations"]

    if str(data.get("context_id")) == str(context_id):
        context = mongo.db.contexts.find_one({"context_id": ObjectId(context_id)})
    if not context:
        return abort(404, "Context no trobat.")
    
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Required fields are missing."}), 400
    
    context_id = data.get("context_id")
    policy_text = data.get("policy_text")
    reasons = data.get("reasons", [])
    recommendations = data.get("recommendations", [])
    language = data.get("language", "")
    version = data.get("policy_agent_version", "")
    
    # Construim prompt per al rol IMQ "One or Incremental Model Query"
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

        # Actualitzem el document amb el prompt actualitzat
        # TODO:guardar totes les iteracions per traçabilitat.
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
