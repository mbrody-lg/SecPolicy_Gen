"""Service helpers for validator orchestration and policy-agent communication."""

import logging
import os

import requests
from flask import current_app, has_app_context, has_request_context, request

from app.agents.roles.coordinator import Coordinator


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
VALIDATION_REQUIRED_FIELDS = ["context_id", "policy_text", "structured_plan", "generated_at"]
logger = logging.getLogger(__name__)


def _error_payload(
    *,
    error_type: str,
    error_code: str,
    message: str,
    details: dict | None = None,
    correlation_id: str | None = None,
) -> dict:
    body = {
        "success": False,
        "error_type": error_type,
        "error_code": error_code,
        "message": message,
        "details": details or {},
    }
    if correlation_id:
        body["correlation_id"] = correlation_id
    return body


class PipelineStepError(Exception):
    """Structured validator error used to keep orchestration failures explicit."""

    def __init__(
        self,
        *,
        stage: str,
        message: str,
        error_type: str,
        error_code: str,
        status_code: int,
        details: dict | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.error_type = error_type
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        self.correlation_id = correlation_id


def _get_correlation_id(payload: dict | None) -> str | None:
    header_correlation_id = request.headers.get("X-Correlation-ID") if has_request_context() else None
    if not isinstance(payload, dict):
        return header_correlation_id
    return header_correlation_id or payload.get("correlation_id") or payload.get("context_id")


def _dependency_headers(correlation_id: str | None) -> dict:
    """Build outbound dependency headers with correlation metadata when available."""
    if not correlation_id:
        return {}
    return {"X-Correlation-ID": correlation_id}


def _dependency_timeout(config_name: str, default: float = 30.0) -> float:
    """Read outbound dependency timeout from app config."""
    timeout_value = current_app.config.get(config_name, default) if has_app_context() else default
    try:
        timeout_seconds = float(timeout_value)
    except (TypeError, ValueError):
        return default
    return timeout_seconds if timeout_seconds > 0 else default


def _dependency_error_details(
    *,
    response: requests.Response | None,
    target_service: str,
    operation: str,
) -> dict:
    """Extract stable dependency error details without leaking raw response bodies."""
    details = {
        "target_service": target_service,
        "operation": operation,
    }
    if response is None:
        return details

    details["dependency_status_code"] = response.status_code
    try:
        body = response.json()
    except ValueError:
        return details

    if isinstance(body, dict):
        if body.get("error_type"):
            details["dependency_error_type"] = body["error_type"]
        if body.get("error_code"):
            details["dependency_error_code"] = body["error_code"]
        if body.get("correlation_id"):
            details["dependency_correlation_id"] = body["correlation_id"]
    return details


def _pipeline_success(*, stage: str, **payload) -> dict:
    result = {"success": True, "stage": stage}
    result.update(payload)
    return result


def _pipeline_error(exc: PipelineStepError) -> dict:
    return _error_payload(
        error_type=exc.error_type,
        error_code=exc.error_code,
        message=exc.message,
        details={"stage": exc.stage, **exc.details},
        correlation_id=exc.correlation_id,
    ) | {"status_code": exc.status_code}


def validate_policy_payload(payload: dict) -> dict:
    """Validate request contract, run coordinator orchestration, and normalize response."""
    correlation_id = _get_correlation_id(payload)
    missing = [field for field in VALIDATION_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise PipelineStepError(
            stage="contract_validation",
            message="Required fields are missing.",
            error_type="contract_error",
            error_code="missing_required_fields",
            status_code=400,
            details={"missing_fields": missing},
            correlation_id=correlation_id,
        )

    try:
        coordinator = Coordinator()
        validation_result = coordinator.validate_policy(payload)
    except PipelineStepError:
        raise
    except Exception as exc:
        logger.exception("Validator execution failed for context_id=%s", payload.get("context_id"))
        raise PipelineStepError(
            stage="validation",
            message="Validator execution failed.",
            error_type="internal_error",
            error_code="validation_execution_failed",
            status_code=500,
            details={"operation": "validate_policy"},
            correlation_id=correlation_id,
        ) from exc

    if validation_result.get("success") is False:
        status_code = 502 if validation_result.get("error_type") == "dependency_error" else 500
        raise PipelineStepError(
            stage="validation",
            message=validation_result.get("message", "Validator execution failed."),
            error_type=validation_result.get("error_type", "internal_error"),
            error_code=validation_result.get("error_code", "validation_execution_failed"),
            status_code=status_code,
            details=validation_result.get("details", {}),
            correlation_id=validation_result.get("correlation_id", correlation_id),
        )

    response = {
        "context_id": payload["context_id"],
        "language": validation_result.get("language", payload.get("language", "")),
        "policy_text": validation_result.get("policy_text", payload["policy_text"]),
        "structured_plan": payload["structured_plan"],
        "generated_at": validation_result.get("generated_at", payload["generated_at"]),
        "policy_agent_version": validation_result.get(
            "policy_agent_version",
            payload.get("policy_agent_version", ""),
        ),
        "status": validation_result.get("status", "review"),
        "reasons": validation_result.get("reasons", []),
        "recommendations": validation_result.get("recommendations", []),
    }
    if "evaluator_analysis" in validation_result:
        response["evaluator_analysis"] = validation_result["evaluator_analysis"]

    return _pipeline_success(stage="completed", validation=response)


def run_validation_pipeline(payload: dict) -> dict:
    """Execute validator pipeline and return structured success or error envelopes."""
    try:
        return validate_policy_payload(payload)
    except PipelineStepError as exc:
        return _pipeline_error(exc)


def send_policy_update_to_policy_agent(
    context_id: str,
    language: str,
    policy_text: str,
    policy_agent_version: str,
    generated_at: str,
    status: str,
    reasons: list,
    recommendations: list,
):
    """Send validator feedback to policy-agent and return the revised policy payload."""
    policy_agent_url = os.getenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    update_endpoint = f"{policy_agent_url}/generate_policy/{context_id}/update"

    payload = {
        "context_id": context_id,
        "language": language,
        "policy_text": policy_text,
        "policy_agent_version": policy_agent_version,
        "generated_at": generated_at,
        "status": status,
        "reasons": reasons,
        "recommendations": recommendations,
    }
    correlation_id = _get_correlation_id(payload)
    timeout_seconds = _dependency_timeout("POLICY_AGENT_TIMEOUT_SECONDS")

    try:
        response = requests.post(
            update_endpoint,
            json=payload,
            headers=_dependency_headers(correlation_id),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        response = exc.response if isinstance(exc, requests.exceptions.HTTPError) else None
        logger.warning(
            "Policy update request failed for context_id=%s target=%s",
            context_id,
            update_endpoint,
            exc_info=exc,
        )
        return _error_payload(
            error_type="dependency_error",
            error_code="policy_update_request_failed",
            message="Error sending policy update to policy-agent.",
            details=_dependency_error_details(
                response=response,
                target_service="policy-agent",
                operation="generate_policy_update",
            )
            | {"request_fields": POLICY_UPDATE_REQUIRED_FIELDS},
            correlation_id=correlation_id or context_id,
        )
