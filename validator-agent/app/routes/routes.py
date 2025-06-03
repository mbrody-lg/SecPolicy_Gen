from flask import Blueprint, request, jsonify, abort, current_app
from bson import ObjectId
from app import mongo
from app.agents.roles.coordinator import Coordinator
import traceback

routes = Blueprint("routes", __name__)

@routes.route("/validate-policy", methods=["POST"])
def validate_policy():
    try:
        data = request.get_json(force=True)

        required_fields = ["context_id", "policy_text", "structured_plan", "generated_at"]
        missing = [field for field in required_fields if field not in data]

        if missing:
            return jsonify({
                "error": f"Missing required fields from policy-agent output: {', '.join(missing)}"
            }), 400

        # Executar la validació
        coordinator = Coordinator()
        validation_result = coordinator.validate_policy(data)

        # DEBUG opcional
        if coordinator.debug_mode:
            print(f'\nVALIDATION_RESULT:\n{validation_result}\n')

        # Retornar resposta completa, tant si és acceptada com si no
        response = {
            "context_id": data["context_id"],
            "language": data.get("language", ""),
            "policy_text": data["policy_text"],
            "structured_plan": data["structured_plan"],
            "generated_at": data["generated_at"],
            "policy_agent_version": data.get("policy_agent_version", ""),
            "status": validation_result.get("status", "review"),
            "reasons": validation_result.get("reasons", []),
            "recommendations": validation_result.get("recommendations", []),
        }

        if "evaluator_analysis" in validation_result:
            response["evaluator_analysis"] = validation_result["evaluator_analysis"]

        return jsonify(response), 200

    except Exception as e:
        print("EXCEPTION:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@routes.route("/validation/<context_id>", methods=["GET"])
def get_validations_by_context(context_id):
    try:
        object_id = ObjectId(context_id)
    except Exception:
        print("EXCEPTION:")
        traceback.print_exc()
        return jsonify({"error": "Invalid context_id format."}), 400

    validations = list(mongo.db.validations.find({"context_id": context_id}).sort("round", 1))

    if not validations:
        return jsonify({"message": "No validation records found for this context."}), 404

    # Serialitzar els ObjectId i timestamps per JSON
    for v in validations:
        v["_id"] = str(v["_id"])
        v["context_id"] = str(v["context_id"])
        if "timestamp" in v:
            v["timestamp"] = v["timestamp"].isoformat()

    return jsonify(validations), 200

@routes.route("/validation/<context_id>", methods=["DELETE"])
def delete_validations_by_context(context_id):
    if not current_app.config.get("TESTING", False):
        abort(403, "This operation is only allowed in DEBUG mode.")

    try:
        object_id = ObjectId(context_id)
    except Exception:
        print("EXCEPTION:")
        traceback.print_exc()
        return jsonify({"error": "Invalid context_id format."}), 400

    result = mongo.db.validations.delete_many({"context_id": context_id})

    if result.deleted_count == 0:
        return jsonify({"message": "No validation records found for this context."}), 404

    return jsonify({
        "message": f"{result.deleted_count} validation(s) deleted for context_id: {context_id}"
    }), 200
