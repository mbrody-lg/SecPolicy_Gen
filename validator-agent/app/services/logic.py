"""Service helpers for validator orchestration and policy-agent communication."""

import logging
import os
from pathlib import Path

import requests
from flask import current_app, g, has_app_context, has_request_context, request
import yaml

from app.agents.roles.coordinator import Coordinator
from app import mongo
from app.observability import build_log_event, log_event


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
MAX_CONTEXT_ID_LENGTH = 128
MAX_LANGUAGE_LENGTH = 16
MAX_POLICY_TEXT_LENGTH = 50000
MAX_POLICY_AGENT_VERSION_LENGTH = 64
MAX_GENERATED_AT_LENGTH = 64
MAX_RETRIEVAL_EVIDENCE_ITEMS = 50
MAX_RETRIEVAL_EVIDENCE_FIELD_LENGTH = 5000


def get_health_status() -> dict:
    """Return a lightweight liveness payload for validator-agent."""
    return {
        "status": "ok",
        "service": "validator-agent",
    }


def get_readiness_status() -> dict:
    """Validate the minimum dependencies needed to serve validator requests."""
    checks = {}
    errors = []

    try:
        mongo.db.command("ping")
        checks["mongo"] = "ok"
    except Exception:  # pragma: no cover - pymongo-specific failure shapes
        logger.exception("Validator readiness failed while checking mongo.")
        checks["mongo"] = "error"
        errors.append("mongo_unavailable")

    config_path = current_app.config.get("CONFIG_PATH", "")
    try:
        if not config_path or not Path(config_path).exists():
            raise FileNotFoundError(config_path)
        with open(config_path, "r", encoding="utf-8") as config_file:
            yaml.safe_load(config_file)
        checks["config"] = "ok"
    except Exception:
        logger.exception("Validator readiness failed while loading config path=%s", config_path)
        checks["config"] = "error"
        errors.append("config_unavailable")

    if errors:
        return _error_payload(
            error_type="dependency_error",
            error_code="service_not_ready",
            message="Validator-agent readiness checks failed.",
            details={"checks": checks, "errors": errors},
        ) | {"status_code": 503}

    return {
        "success": True,
        "status": "ready",
        "service": "validator-agent",
        "checks": checks,
    }


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
    request_correlation_id = getattr(g, "correlation_id", None) if has_request_context() else None
    header_correlation_id = request.headers.get("X-Correlation-ID") if has_request_context() else None
    if not isinstance(payload, dict):
        return request_correlation_id or header_correlation_id
    return request_correlation_id or header_correlation_id or payload.get("correlation_id") or payload.get("context_id")


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


def _ensure_payload_object(payload: dict | None, correlation_id: str | None) -> dict:
    if not isinstance(payload, dict):
        raise PipelineStepError(
            stage="contract_validation",
            message="Request body must be a JSON object.",
            error_type="contract_error",
            error_code="invalid_json_body",
            status_code=400,
            details={"expected_type": "object"},
            correlation_id=correlation_id,
        )
    return payload


def _require_string_field(
    payload: dict,
    *,
    field: str,
    max_length: int,
    correlation_id: str | None,
    allow_empty: bool = False,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise PipelineStepError(
            stage="contract_validation",
            message=f"Field '{field}' must be a string.",
            error_type="contract_error",
            error_code="invalid_field_type",
            status_code=400,
            details={"field": field, "expected_type": "string"},
            correlation_id=correlation_id,
        )

    normalized = value.strip()
    if not allow_empty and not normalized:
        raise PipelineStepError(
            stage="contract_validation",
            message=f"Field '{field}' must not be empty.",
            error_type="contract_error",
            error_code="empty_required_field",
            status_code=400,
            details={"field": field},
            correlation_id=correlation_id,
        )

    if len(normalized) > max_length:
        raise PipelineStepError(
            stage="contract_validation",
            message=f"Field '{field}' exceeds the allowed size.",
            error_type="contract_error",
            error_code="field_too_large",
            status_code=413,
            details={"field": field, "max_length": max_length},
            correlation_id=correlation_id,
        )
    return normalized


def _validate_retrieval_evidence(value: object, *, correlation_id: str | None) -> list[dict]:
    """Validate optional RAG evidence supplied by policy-agent."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise PipelineStepError(
            stage="contract_validation",
            message="Field 'retrieval_evidence' must be a list.",
            error_type="contract_error",
            error_code="invalid_field_type",
            status_code=400,
            details={"field": "retrieval_evidence", "expected_type": "list[object]"},
            correlation_id=correlation_id,
        )
    if len(value) > MAX_RETRIEVAL_EVIDENCE_ITEMS:
        raise PipelineStepError(
            stage="contract_validation",
            message="Field 'retrieval_evidence' exceeds the allowed item count.",
            error_type="contract_error",
            error_code="field_too_large",
            status_code=413,
            details={"field": "retrieval_evidence", "max_items": MAX_RETRIEVAL_EVIDENCE_ITEMS},
            correlation_id=correlation_id,
        )

    normalized = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise PipelineStepError(
                stage="contract_validation",
                message="Field 'retrieval_evidence' must contain only objects.",
                error_type="contract_error",
                error_code="invalid_field_type",
                status_code=400,
                details={"field": "retrieval_evidence", "index": index, "expected_type": "object"},
                correlation_id=correlation_id,
            )
        normalized.append(_normalize_evidence_item(item, index, correlation_id))
    return normalized


def _normalize_evidence_item(item: dict, index: int, correlation_id: str | None) -> dict:
    normalized = {}
    for field in ("citation", "source_id", "collection", "family", "document_id", "text"):
        value = item.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise PipelineStepError(
                stage="contract_validation",
                message=f"Field 'retrieval_evidence[{index}].{field}' must be a string.",
                error_type="contract_error",
                error_code="invalid_field_type",
                status_code=400,
                details={"field": "retrieval_evidence", "index": index, "key": field, "expected_type": "string"},
                correlation_id=correlation_id,
            )
        if len(value) > MAX_RETRIEVAL_EVIDENCE_FIELD_LENGTH:
            raise PipelineStepError(
                stage="contract_validation",
                message=f"Field 'retrieval_evidence[{index}].{field}' exceeds the allowed size.",
                error_type="contract_error",
                error_code="field_too_large",
                status_code=413,
                details={
                    "field": "retrieval_evidence",
                    "index": index,
                    "key": field,
                    "max_length": MAX_RETRIEVAL_EVIDENCE_FIELD_LENGTH,
                },
                correlation_id=correlation_id,
            )
        normalized[field] = value

    score = item.get("score")
    if isinstance(score, (int, float)):
        normalized["score"] = score
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        normalized["metadata"] = metadata
    return normalized


def validate_policy_payload(payload: dict | None) -> dict:
    """Validate request contract, run coordinator orchestration, and normalize response."""
    correlation_id = _get_correlation_id(payload)
    data = _ensure_payload_object(payload, correlation_id)
    log_event(
        logger,
        logging.INFO,
        event="validator.pipeline.started",
        stage="validation",
        context_id=data.get("context_id"),
        correlation_id=correlation_id,
    )
    missing = [field for field in VALIDATION_REQUIRED_FIELDS if field not in data]
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

    normalized_payload = {
        "context_id": _require_string_field(
            data,
            field="context_id",
            max_length=MAX_CONTEXT_ID_LENGTH,
            correlation_id=correlation_id,
        ),
        "policy_text": _require_string_field(
            data,
            field="policy_text",
            max_length=MAX_POLICY_TEXT_LENGTH,
            correlation_id=correlation_id,
        ),
        "generated_at": _require_string_field(
            data,
            field="generated_at",
            max_length=MAX_GENERATED_AT_LENGTH,
            correlation_id=correlation_id,
        ),
        "structured_plan": data["structured_plan"],
        "retrieval_evidence": _validate_retrieval_evidence(
            data.get("retrieval_evidence"),
            correlation_id=correlation_id,
        ),
    }
    if "language" in data:
        normalized_payload["language"] = _require_string_field(
            data,
            field="language",
            max_length=MAX_LANGUAGE_LENGTH,
            correlation_id=correlation_id,
        )
    if "policy_agent_version" in data:
        normalized_payload["policy_agent_version"] = _require_string_field(
            data,
            field="policy_agent_version",
            max_length=MAX_POLICY_AGENT_VERSION_LENGTH,
            correlation_id=correlation_id,
        )
    if correlation_id:
        normalized_payload["correlation_id"] = correlation_id

    try:
        coordinator = Coordinator()
        validation_result = coordinator.validate_policy(normalized_payload)
    except PipelineStepError:
        raise
    except Exception as exc:
        logger.exception(
            build_log_event(
                event="validator.pipeline.failed",
                stage="validation",
                context_id=normalized_payload.get("context_id"),
                correlation_id=correlation_id,
                error_code="validation_execution_failed",
            )
        )
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
        "context_id": normalized_payload["context_id"],
        "language": validation_result.get("language", normalized_payload.get("language", "")),
        "policy_text": validation_result.get("policy_text", normalized_payload["policy_text"]),
        "structured_plan": normalized_payload["structured_plan"],
        "retrieval_evidence": validation_result.get(
            "retrieval_evidence",
            normalized_payload.get("retrieval_evidence", []),
        ),
        "generated_at": validation_result.get("generated_at", normalized_payload["generated_at"]),
        "policy_agent_version": validation_result.get(
            "policy_agent_version",
            normalized_payload.get("policy_agent_version", ""),
        ),
        "status": validation_result.get("status", "review"),
        "reasons": validation_result.get("reasons", []),
        "recommendations": validation_result.get("recommendations", []),
    }
    if "evaluator_analysis" in validation_result:
        response["evaluator_analysis"] = validation_result["evaluator_analysis"]

    log_event(
        logger,
        logging.INFO,
        event="validator.pipeline.completed",
        stage="completed",
        context_id=normalized_payload["context_id"],
        correlation_id=correlation_id,
        result="success",
        validation_status=response["status"],
    )
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
    policy_agent_url = (
        current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
        if has_app_context()
        else os.getenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    )
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
    log_event(
        logger,
        logging.INFO,
        event="validator.policy_update.request",
        stage="policy_update",
        context_id=context_id,
        correlation_id=correlation_id,
        target_service="policy-agent",
        operation="generate_policy_update",
        timeout_seconds=timeout_seconds,
    )

    try:
        response = requests.post(
            update_endpoint,
            json=payload,
            headers=_dependency_headers(correlation_id),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        log_event(
            logger,
            logging.INFO,
            event="validator.policy_update.response",
            stage="policy_update",
            context_id=context_id,
            correlation_id=correlation_id,
            target_service="policy-agent",
            operation="generate_policy_update",
            status_code=response.status_code,
            result="success",
        )
        return response.json()
    except requests.exceptions.RequestException as exc:
        response = exc.response if isinstance(exc, requests.exceptions.HTTPError) else None
        logger.warning(
            build_log_event(
                event="validator.policy_update.response",
                stage="policy_update",
                context_id=context_id,
                correlation_id=correlation_id,
                target_service="policy-agent",
                operation="generate_policy_update",
                status_code=response.status_code if response is not None else None,
                result="failure",
                target=update_endpoint,
            ),
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
