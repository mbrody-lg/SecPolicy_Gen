"""HTTP routes for policy generation and policy revision workflow."""

from flask import Blueprint, jsonify, request

from app.services.logic import (
    get_health_status,
    get_readiness_status,
    get_rag_runtime_status,
    refresh_rag_runtime,
    run_generation_pipeline,
    run_policy_update_pipeline,
)


routes = Blueprint("routes", __name__)


@routes.route("/health", methods=["GET"])
def health():
    """Return a lightweight liveness signal for the policy-agent service."""
    return jsonify(get_health_status()), 200


@routes.route("/ready", methods=["GET"])
def ready():
    """Return readiness based on minimal safe dependency and config checks."""
    payload, status_code = get_readiness_status()
    return jsonify(payload), status_code


@routes.route("/rag/status", methods=["GET"])
def rag_status():
    """Return RAG runtime status and missing configured Chroma collections."""
    payload, status_code = get_rag_runtime_status()
    return jsonify(payload), status_code


@routes.route("/rag/refresh", methods=["POST"])
def rag_refresh():
    """Run the controlled local RAG refresh action when enabled."""
    payload, status_code = refresh_rag_runtime()
    return jsonify(payload), status_code


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
