"""HTTP routes for policy generation and policy revision workflow."""

import logging

from flask import Blueprint, jsonify, request

from app.metrics import metrics_response
from app.observability import log_event
from app.services.logic import (
    get_health_status,
    get_readiness_status,
    get_rag_runtime_status,
    refresh_rag_runtime,
    run_generation_pipeline,
    run_policy_update_pipeline,
)


routes = Blueprint("routes", __name__)
logger = logging.getLogger(__name__)


@routes.route("/health", methods=["GET"])
def health():
    """Return a lightweight liveness signal for the policy-agent service."""
    return jsonify(get_health_status()), 200


@routes.route("/ready", methods=["GET"])
def ready():
    """Return readiness based on minimal safe dependency and config checks."""
    payload, status_code = get_readiness_status()
    _log_readiness_response(payload, status_code)
    return jsonify(payload), status_code


@routes.route("/metrics", methods=["GET"])
def metrics():
    """Expose Prometheus metrics for local observability."""
    return metrics_response()


def _log_readiness_response(payload: dict, status_code: int) -> None:
    """Emit a bounded structured event for readiness responses."""
    is_ready = payload.get("status") == "ready"
    log_event(
        logger,
        logging.INFO if is_ready else logging.WARNING,
        event="readiness.route.completed",
        stage="readiness",
        route="/ready",
        method="GET",
        status_code=status_code,
        result="success" if is_ready else "failure",
        readiness_status=payload.get("status", "unknown"),
        error_code=None if is_ready else "service_not_ready",
    )


@routes.route("/rag/status", methods=["GET"])
def rag_status():
    """Return RAG runtime status and missing configured Chroma collections."""
    payload, status_code = get_rag_runtime_status()
    log_event(
        logger,
        logging.INFO if status_code < 400 else logging.WARNING,
        event="rag.status.route.completed",
        stage="rag_status",
        route="/rag/status",
        method="GET",
        status_code=status_code,
        result="success" if status_code < 400 else "failure",
        rag_status=payload.get("rag", {}).get("status"),
        error_code=None if status_code < 400 else payload.get("rag", {}).get("reason", "rag_not_ready"),
    )
    return jsonify(payload), status_code


@routes.route("/rag/refresh", methods=["POST"])
def rag_refresh():
    """Run the controlled local RAG refresh action when enabled."""
    payload, status_code = refresh_rag_runtime()
    log_event(
        logger,
        logging.INFO if status_code < 400 else logging.WARNING,
        event="rag.refresh.route.completed",
        stage="rag_refresh",
        route="/rag/refresh",
        method="POST",
        status_code=status_code,
        result="success" if status_code < 400 else "failure",
        refresh_status=payload.get("job", {}).get("status"),
        error_code=payload.get("error_code"),
    )
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
