"""HTTP routes for policy generation and policy revision workflow."""

import logging

from flask import Blueprint, g, jsonify, request
from markupsafe import escape

from app.candidate_contract import authorize_candidate_request
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
from app.workload_token import TENANT_PATTERN


routes = Blueprint("routes", __name__)
logger = logging.getLogger(__name__)


def _authoritative_organization_id(scope: str) -> str | None:
    principal = getattr(g, "service_principal", None)
    if not isinstance(principal, dict) or scope not in {"policy:generate", "policy:update"}:
        return None
    expected_identity = "context-agent" if scope == "policy:generate" else "validator-agent"
    if (principal.get("authentication") != "signed_workload_token"
            or principal.get("audience") != "policy-agent"
            or principal.get("identity") != expected_identity):
        return None
    scopes = principal.get("scopes")
    if not isinstance(scopes, list) or scope not in scopes:
        return None
    organization_id = principal.get("tenant_id")
    if not isinstance(organization_id, str) or not TENANT_PATTERN.fullmatch(organization_id):
        return None
    return organization_id


def _tenant_unavailable():
    return jsonify({"success": False, "error_code": "service_authentication_unavailable"}), 503


def _jsonify_escaped(payload):
    """Return JSON with text escaped for safe browser rendering."""
    return jsonify(_escape_json_payload(payload))


def _escape_json_payload(value):
    if isinstance(value, str):
        return str(escape(value))
    if isinstance(value, list):
        return [_escape_json_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_escape_json_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            _escape_json_payload(key): _escape_json_payload(item)
            for key, item in value.items()
        }
    return value


@routes.route("/health", methods=["GET"])
def health():
    """Return a lightweight liveness signal for the policy-agent service."""
    return jsonify(get_health_status()), 200


@routes.route("/ready", methods=["GET"])
def ready():
    """Return readiness based on minimal safe dependency and config checks."""
    payload, status_code = get_readiness_status()
    _log_readiness_response(payload, status_code)
    return _jsonify_escaped(payload), status_code


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
    return _jsonify_escaped(payload), status_code


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
    return _jsonify_escaped(payload), status_code


@routes.route("/generate_policy", methods=["POST"])
def generate_policy():
    """Generate a policy from refined context data via policy-agent pipeline."""
    organization_id = _authoritative_organization_id("policy:generate")
    if organization_id is None:
        return _tenant_unavailable()
    pipeline_result = run_generation_pipeline(
        request.get_json(silent=True), organization_id=organization_id,
    )
    if not pipeline_result["success"]:
        status_code = pipeline_result.pop("status_code")
        return jsonify(pipeline_result), status_code
    return jsonify(pipeline_result["policy"]), 200


@routes.route("/candidate/generate-policy", methods=["POST"])
def generate_candidate_policy():
    """Generate a real policy candidate without writing authoritative state."""
    metadata, contract_error = authorize_candidate_request(
        audience="policy-agent",
        scope="policy:candidate:generate",
    )
    if contract_error:
        payload, status_code = contract_error
        return jsonify(payload), status_code

    candidate_payload = request.get_json(silent=True)
    if isinstance(candidate_payload, dict) and "policy_request" in candidate_payload:
        return jsonify({"success": False, "error_code": "candidate_policy_request_forbidden"}), 400

    pipeline_result = run_generation_pipeline(
        candidate_payload, persist=False,
    )
    if not pipeline_result["success"]:
        status_code = pipeline_result.pop("status_code")
        return jsonify(pipeline_result), status_code

    policy = pipeline_result["policy"]
    policy["candidate"] = {
        "authoritative": False,
        "tenant_id": metadata["tenant_id"],
        "idempotency_key": metadata["idempotency_key"],
    }
    return jsonify(policy), 200


@routes.route("/generate_policy/<context_id>/update", methods=["POST"])
def update_policy(context_id):
    """Regenerate policy text after validator feedback for a context."""
    organization_id = _authoritative_organization_id("policy:update")
    if organization_id is None:
        return _tenant_unavailable()
    pipeline_result = run_policy_update_pipeline(
        request.get_json(silent=True), str(context_id), organization_id=organization_id,
    )
    if not pipeline_result["success"]:
        status_code = pipeline_result.pop("status_code")
        return jsonify(pipeline_result), status_code
    return jsonify(pipeline_result["policy"]), 200
