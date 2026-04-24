"""HTTP routes for policy generation and policy revision workflow."""

from flask import Blueprint, jsonify, request

from app.services.logic import run_generation_pipeline, run_policy_update_pipeline


routes = Blueprint("routes", __name__)


@routes.route("/generate_policy", methods=["POST"])
def generate_policy():
    """Generate a policy from refined context data via policy-agent pipeline."""
    pipeline_result = run_generation_pipeline(request.get_json(silent=True))
    if not pipeline_result["success"]:
        status_code = pipeline_result.pop("status_code")
        return jsonify(pipeline_result), status_code
    return jsonify(pipeline_result["policy"]), 200


@routes.route("/generate_policy/<context_id>/update", methods=["POST"])
def update_policy(context_id):
    """Regenerate policy text after validator feedback for a context."""
    pipeline_result = run_policy_update_pipeline(request.get_json(silent=True), str(context_id))
    if not pipeline_result["success"]:
        status_code = pipeline_result.pop("status_code")
        return jsonify(pipeline_result), status_code
    return jsonify(pipeline_result["policy"]), 200
