"""Service helpers for context prompting and policy pipeline orchestration."""

from datetime import datetime, timezone
import logging
from time import perf_counter

import requests
import yaml
from bson import ObjectId
from flask import current_app
from markdown import markdown

from app import get_request_correlation_id, mongo
from app.agents.factory import create_agent_from_config
from app.observability import build_log_event, log_event

logger = logging.getLogger(__name__)
MAX_PIPELINE_DIAGNOSTIC_HOPS = 25


class PipelineStepError(Exception):
    """Structured pipeline error used to keep orchestration failures explicit."""

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


def get_health_status() -> dict:
    """Return a lightweight liveness payload without touching dependencies."""
    return {
        "status": "ok",
        "service": "context-agent",
    }


def _required_readiness_config() -> dict[str, str]:
    """Return the minimal config keys needed for this service to operate safely."""
    return {
        "SECRET_KEY": current_app.config.get("SECRET_KEY"),
        "MONGO_URI": current_app.config.get("MONGO_URI"),
    }


def _config_readiness_check() -> dict:
    """Validate essential runtime configuration."""
    missing = sorted(
        key for key, value in _required_readiness_config().items()
        if value is None or str(value).strip() == ""
    )
    return {
        "status": "ok" if not missing else "error",
        "missing": missing,
    }


def _mongo_readiness_check() -> dict:
    """Validate MongoDB connectivity with a safe ping."""
    try:
        mongo.cx.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        return {
            "status": "error",
            "reason": "ping_failed",
        }


def get_readiness_status() -> dict:
    """Return service readiness based on essential config and Mongo reachability."""
    config_check = _config_readiness_check()
    mongo_check = _mongo_readiness_check()
    checks = {
        "config": config_check,
        "mongo": mongo_check,
    }
    is_ready = all(check["status"] == "ok" for check in checks.values())
    return {
        "status": "ready" if is_ready else "not_ready",
        "service": "context-agent",
        "checks": checks,
    }


def load_questions(config_path="app/config/context_questions.yaml"):
    """Load context-question definitions from YAML configuration."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]


def generate_context_prompt(data: dict, question_config="app/config/context_questions.yaml") -> str:
    """
    Build a text prompt from form answers.
    This prompt is used to drive context generation.
    """
    questions = load_questions(question_config)

    lines = ["This is the context obtained from the questions asked:"]
    for q in questions:
        key = q["id"]
        answer = data.get(key, "").strip()
        if answer:
            lines.append(f"- {q['question']} {answer}")
    lines.append(
        "This context will be used by other agents to generate policies, security frameworks or specific validations."
    )
    return "\n".join(lines)


def run_with_agent(prompt: str, context_id: str = None, model_version: str = None) -> str:
    """
    Execute the configured agent using the initial prompt.
    The context_id can be used for session naming, assistant_id, or traceability.
    """
    config_path = "app/config/context_agent.yaml"
    _ = model_version
    agent = create_agent_from_config(config_path)
    agent.create(context_id=context_id)  # pass context_id when persistence is needed
    return agent.run(prompt, context_id)


def _result_error(error: str, details: str = "", status_code: int = 500) -> dict:
    return {"success": False, "error": error, "details": details, "status_code": status_code}


def _pipeline_success(*, stage: str, **payload) -> dict:
    result = {"success": True, "stage": stage}
    result.update(payload)
    return result


def _pipeline_error(exc: PipelineStepError) -> dict:
    payload = {
        "success": False,
        "stage": exc.stage,
        "error_type": exc.error_type,
        "error_code": exc.error_code,
        "message": exc.message,
        "details": exc.details,
        "status_code": exc.status_code,
    }
    correlation_id = exc.correlation_id or _get_correlation_id()
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload


def _get_correlation_id(payload: dict | None = None, context_id: str | None = None) -> str | None:
    """Resolve correlation id from the request boundary or current payload/context."""
    request_correlation_id = get_request_correlation_id()
    if request_correlation_id:
        return request_correlation_id
    if isinstance(payload, dict) and payload.get("correlation_id"):
        return str(payload["correlation_id"])
    if isinstance(payload, dict) and payload.get("context_id"):
        return str(payload["context_id"])
    if context_id:
        return str(context_id)
    return None


def _dependency_headers(correlation_id: str | None) -> dict:
    """Build outbound service headers with correlation metadata when available."""
    if not correlation_id:
        return {}
    return {"X-Correlation-ID": correlation_id}


def _dependency_timeout(config_name: str, default: float = 30.0) -> float:
    """Read outbound dependency timeout from app config."""
    timeout_value = current_app.config.get(config_name, default)
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


def _pipeline_diagnostics_collection():
    """Return the collection used for bounded pipeline diagnostics."""
    return mongo.db.pipeline_diagnostics


def _upsert_pipeline_diagnostic(
    *,
    correlation_id: str | None,
    context_id: str | None,
    hop: dict,
    status: str | None = None,
    last_error: dict | None = None,
    completed: bool = False,
) -> None:
    """Persist a bounded cross-service diagnostic view keyed by correlation id."""
    if not correlation_id:
        return

    now = datetime.now(timezone.utc)
    update_doc = {
        "$setOnInsert": {
            "correlation_id": correlation_id,
            "created_at": now,
            "ownership": {
                "owner_service": "context-agent",
                "source_of_truth": False,
                "collection": "pipeline_diagnostics",
                "view_type": "pipeline_diagnostic",
            },
        },
        "$set": {
            "context_id": context_id,
            "updated_at": now,
        },
        "$push": {"hops": {"$each": [hop], "$slice": -MAX_PIPELINE_DIAGNOSTIC_HOPS}},
    }
    if status is not None:
        update_doc["$set"]["status"] = status
    if last_error is not None:
        update_doc["$set"]["last_error"] = last_error
    if completed:
        update_doc["$set"]["completed_at"] = now

    try:
        _pipeline_diagnostics_collection().update_one(
            {"correlation_id": correlation_id},
            update_doc,
            upsert=True,
        )
    except Exception:
        logger.warning(
            build_log_event(
                event="context.pipeline_diagnostic.persistence_failed",
                stage="diagnostics",
                context_id=context_id,
                correlation_id=correlation_id,
            ),
            exc_info=True,
        )


def get_pipeline_diagnostic(correlation_id: str) -> dict | None:
    """Return a persisted pipeline diagnostic document by correlation id."""
    diagnostic = _pipeline_diagnostics_collection().find_one({"correlation_id": correlation_id})
    if not diagnostic:
        return None
    if "_id" in diagnostic:
        diagnostic["_id"] = str(diagnostic["_id"])
    for field in ("created_at", "updated_at", "completed_at"):
        if field in diagnostic and hasattr(diagnostic[field], "isoformat"):
            diagnostic[field] = diagnostic[field].isoformat()
    for hop in diagnostic.get("hops", []):
        for field in ("started_at", "completed_at"):
            if field in hop and hasattr(hop[field], "isoformat"):
                hop[field] = hop[field].isoformat()
    return diagnostic


def get_context_and_prompt(context_id: str) -> dict:
    """Fetch context data and the refined prompt required by policy-agent."""
    correlation_id = _get_correlation_id(context_id=context_id)
    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise PipelineStepError(
            stage="context_fetch",
            message="Invalid context_id format.",
            error_type="contract_error",
            error_code="invalid_context_id",
            status_code=400,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        ) from exc

    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        raise PipelineStepError(
            stage="context_fetch",
            message="Context not found.",
            error_type="validation_error",
            error_code="context_not_found",
            status_code=404,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        )

    refined_prompt = (context.get("refined_prompt") or "").strip()
    if not refined_prompt:
        prompt_entry = mongo.db.interactions.find_one(
            {"context_id": context_obj_id, "question_id": "refined_prompt"}
        )
        if not prompt_entry:
            if "refined_prompt" in context:
                raise PipelineStepError(
                    stage="context_fetch",
                    message="Refined prompt is empty.",
                    error_type="validation_error",
                    error_code="empty_refined_prompt",
                    status_code=400,
                    details={"context_id": context_id},
                    correlation_id=correlation_id,
                )
            raise PipelineStepError(
                stage="context_fetch",
                message="Refined prompt not found.",
                error_type="validation_error",
                error_code="refined_prompt_not_found",
                status_code=404,
                details={"context_id": context_id},
                correlation_id=correlation_id,
            )

        refined_prompt = prompt_entry.get("answer", "").strip()
        if not refined_prompt:
            raise PipelineStepError(
                stage="context_fetch",
                message="Refined prompt is empty.",
                error_type="validation_error",
                error_code="empty_refined_prompt",
                status_code=400,
                details={"context_id": context_id},
                correlation_id=correlation_id,
            )

    return {
        "context_id": context_id,
        "refined_prompt": refined_prompt,
        "language": context.get("language", "en"),
        "model_version": str(context.get("version", "0.1.0")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }


def call_policy_agent(context_payload: dict) -> dict:
    """Call policy-agent and return parsed JSON response."""
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    correlation_id = _get_correlation_id(context_payload)
    timeout_seconds = _dependency_timeout("POLICY_AGENT_TIMEOUT_SECONDS")
    started_at = datetime.now(timezone.utc)
    started_perf = perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="context.policy.request",
        stage="policy_generation",
        context_id=context_payload.get("context_id"),
        correlation_id=correlation_id,
        target_service="policy-agent",
        operation="generate_policy",
        timeout_seconds=timeout_seconds,
    )
    try:
        response = requests.post(
            f"{policy_agent_url}/generate_policy",
            json=context_payload,
            headers=_dependency_headers(correlation_id),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        completed_at = datetime.now(timezone.utc)
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=context_payload.get("context_id"),
            status="in_progress",
            hop={
                "service": "context-agent",
                "stage": "policy_generation",
                "operation": "generate_policy",
                "target_service": "policy-agent",
                "outcome": "success",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code,
            },
        )
        log_event(
            logger,
            logging.INFO,
            event="context.policy.response",
            stage="policy_generation",
            context_id=context_payload.get("context_id"),
            correlation_id=correlation_id,
            target_service="policy-agent",
            operation="generate_policy",
            status_code=response.status_code,
            result="success",
        )
        return response.json()
    except requests.exceptions.RequestException as exc:
        response = exc.response if isinstance(exc, requests.exceptions.HTTPError) else None
        completed_at = datetime.now(timezone.utc)
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=context_payload.get("context_id"),
            status="failed",
            last_error={
                "stage": "policy_generation",
                "error_type": "dependency_error",
                "error_code": "policy_agent_request_failed",
            },
            hop={
                "service": "context-agent",
                "stage": "policy_generation",
                "operation": "generate_policy",
                "target_service": "policy-agent",
                "outcome": "failure",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code if response is not None else None,
                "error_type": "dependency_error",
                "error_code": "policy_agent_request_failed",
            },
        )
        logger.warning(
            build_log_event(
                event="context.policy.response",
                stage="policy_generation",
                context_id=context_payload.get("context_id"),
                correlation_id=correlation_id,
                target_service="policy-agent",
                operation="generate_policy",
                status_code=response.status_code if response is not None else None,
                result="failure",
            ),
            exc_info=exc,
        )
        raise PipelineStepError(
            stage="policy_generation",
            message="Policy generation failed.",
            error_type="dependency_error",
            error_code="policy_agent_request_failed",
            status_code=502,
            details=_dependency_error_details(
                response=response,
                target_service="policy-agent",
                operation="generate_policy",
            ),
            correlation_id=correlation_id,
        ) from exc


def trigger_policy_generation(context_id: str) -> dict:
    """Generate policy data from stored context and refined prompt."""
    log_event(
        logger,
        logging.INFO,
        event="context.pipeline.policy_generation_started",
        stage="policy_generation",
        context_id=context_id,
        correlation_id=_get_correlation_id(context_id=context_id),
    )
    try:
        payload = get_context_and_prompt(context_id)
        policy_data = call_policy_agent(payload)
        log_event(
            logger,
            logging.INFO,
            event="context.pipeline.policy_generation_completed",
            stage="policy_generation",
            context_id=context_id,
            correlation_id=_get_correlation_id(payload, context_id),
            result="success",
        )
        return _pipeline_success(stage="policy_generation", policy_data=policy_data)
    except PipelineStepError as exc:
        return _pipeline_error(exc)
    except Exception as exc:  # unexpected errors
        logger.exception("Unexpected policy generation failure for context_id=%s", context_id)
        return _pipeline_error(
            PipelineStepError(
                stage="policy_generation",
                message="Policy generation failed.",
                error_type="internal_error",
                error_code="policy_generation_unexpected_failure",
                status_code=500,
                details={"operation": "trigger_policy_generation"},
                correlation_id=_get_correlation_id(context_id=context_id),
            )
        )


def call_validator_agent(policy_data: dict) -> dict:
    """Call validator-agent and return parsed JSON response."""
    validator_agent_url = current_app.config.get("VALIDATOR_AGENT_URL", "http://validator-agent:5000")
    correlation_id = _get_correlation_id(policy_data)
    timeout_seconds = _dependency_timeout("VALIDATOR_AGENT_TIMEOUT_SECONDS")
    started_at = datetime.now(timezone.utc)
    started_perf = perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="context.validator.request",
        stage="validation",
        context_id=policy_data.get("context_id"),
        correlation_id=correlation_id,
        target_service="validator-agent",
        operation="validate_policy",
        timeout_seconds=timeout_seconds,
    )
    try:
        response = requests.post(
            f"{validator_agent_url}/validate-policy",
            json=policy_data,
            headers=_dependency_headers(correlation_id),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        completed_at = datetime.now(timezone.utc)
        response_body = response.json()
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=policy_data.get("context_id"),
            status="in_progress",
            hop={
                "service": "context-agent",
                "stage": "validation",
                "operation": "validate_policy",
                "target_service": "validator-agent",
                "outcome": "success",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code,
                "validation_status": response_body.get("status") if isinstance(response_body, dict) else None,
            },
        )
        log_event(
            logger,
            logging.INFO,
            event="context.validator.response",
            stage="validation",
            context_id=policy_data.get("context_id"),
            correlation_id=correlation_id,
            target_service="validator-agent",
            operation="validate_policy",
            status_code=response.status_code,
            result="success",
        )
        return response_body
    except requests.exceptions.RequestException as exc:
        response = exc.response if isinstance(exc, requests.exceptions.HTTPError) else None
        completed_at = datetime.now(timezone.utc)
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=policy_data.get("context_id"),
            status="failed",
            last_error={
                "stage": "validation",
                "error_type": "dependency_error",
                "error_code": "validator_agent_request_failed",
            },
            hop={
                "service": "context-agent",
                "stage": "validation",
                "operation": "validate_policy",
                "target_service": "validator-agent",
                "outcome": "failure",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code if response is not None else None,
                "error_type": "dependency_error",
                "error_code": "validator_agent_request_failed",
            },
        )
        logger.warning(
            build_log_event(
                event="context.validator.response",
                stage="validation",
                context_id=policy_data.get("context_id"),
                correlation_id=correlation_id,
                target_service="validator-agent",
                operation="validate_policy",
                status_code=response.status_code if response is not None else None,
                result="failure",
            ),
            exc_info=exc,
        )
        raise PipelineStepError(
            stage="validation",
            message="Policy validation failed.",
            error_type="dependency_error",
            error_code="validator_agent_request_failed",
            status_code=502,
            details=_dependency_error_details(
                response=response,
                target_service="validator-agent",
                operation="validate_policy",
            ),
            correlation_id=correlation_id,
        ) from exc


def store_validated_policy(context_id: str, validated_data: dict) -> dict:
    """Persist a validated policy payload in context interactions."""
    data = validated_data or {}
    correlation_id = _get_correlation_id(data, context_id)
    required_fields = ["policy_text", "generated_at", "policy_agent_version", "language"]
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise PipelineStepError(
            stage="persistence",
            message="Validated policy payload is incomplete.",
            error_type="contract_error",
            error_code="validated_policy_missing_fields",
            status_code=400,
            details={"missing_fields": missing, "context_id": context_id},
            correlation_id=correlation_id,
        )

    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise PipelineStepError(
            stage="persistence",
            message="Invalid context_id format.",
            error_type="contract_error",
            error_code="invalid_context_id",
            status_code=400,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        ) from exc

    validated_at = datetime.now(timezone.utc)
    mongo.db.interactions.insert_one({
        "context_id": context_obj_id,
        "correlation_id": correlation_id,
        "question_id": "validated_policy",
        "question_text": "Agent-generated policy",
        "answer": data["policy_text"],
        "timestamp": validated_at,
        "origin": "agent",
        "status": data.get("status", "review"),
        "recommendations": data.get("recommendations", []),
        "generated_at": data["generated_at"],
        "policy_agent_version": data["policy_agent_version"],
        "language": data["language"],
        "ownership": {
            "owner_service": "context-agent",
            "source_of_truth": False,
            "view_type": "derived_policy_snapshot",
        },
        "policy_ref": {
            "owner_service": "policy-agent",
            "source_collection": "policies",
            "context_id": context_id,
        },
        "validation_ref": {
            "owner_service": "validator-agent",
            "source_collection": "validations",
            "context_id": context_id,
        },
    })
    _upsert_pipeline_diagnostic(
        correlation_id=correlation_id,
        context_id=context_id,
        status="in_progress",
        hop={
            "service": "context-agent",
            "stage": "persistence",
            "operation": "store_validated_policy",
            "outcome": "success",
            "started_at": validated_at,
            "completed_at": validated_at,
            "duration_ms": 0.0,
        },
    )
    log_event(
        logger,
        logging.INFO,
        event="context.pipeline.persistence_completed",
        stage="persistence",
        context_id=context_id,
        correlation_id=correlation_id,
        result="success",
    )
    return _pipeline_success(
        stage="persistence",
        context_id=context_id,
        stored_at=validated_at.isoformat(),
    )


def generate_full_policy_pipeline(context_id: str) -> dict:
    """Execute policy generation, validation, and context persistence pipeline."""
    correlation_id = _get_correlation_id(context_id=context_id)
    started_at = datetime.now(timezone.utc)
    _upsert_pipeline_diagnostic(
        correlation_id=correlation_id,
        context_id=context_id,
        status="in_progress",
        hop={
            "service": "context-agent",
            "stage": "pipeline",
            "operation": "generate_full_policy_pipeline",
            "outcome": "started",
            "started_at": started_at,
        },
    )
    log_event(
        logger,
        logging.INFO,
        event="context.pipeline.started",
        stage="pipeline",
        context_id=context_id,
        correlation_id=correlation_id,
    )
    try:
        policy_result = trigger_policy_generation(context_id)
        if not policy_result.get("success"):
            _upsert_pipeline_diagnostic(
                correlation_id=policy_result.get("correlation_id", correlation_id),
                context_id=context_id,
                status="failed",
                last_error={
                    "stage": policy_result.get("stage", "policy_generation"),
                    "error_type": policy_result.get("error_type"),
                    "error_code": policy_result.get("error_code"),
                },
                completed=True,
                hop={
                    "service": "context-agent",
                    "stage": policy_result.get("stage", "policy_generation"),
                    "operation": "generate_full_policy_pipeline",
                    "outcome": "failure",
                    "completed_at": datetime.now(timezone.utc),
                    "error_type": policy_result.get("error_type"),
                    "error_code": policy_result.get("error_code"),
                },
            )
            return policy_result

        policy_data = policy_result["policy_data"]
        validated_data = call_validator_agent(policy_data)
        persistence_result = store_validated_policy(context_id, validated_data)
        _upsert_pipeline_diagnostic(
            correlation_id=_get_correlation_id(validated_data, context_id),
            context_id=context_id,
            status="completed",
            completed=True,
            hop={
                "service": "context-agent",
                "stage": "pipeline",
                "operation": "generate_full_policy_pipeline",
                "outcome": "success",
                "completed_at": datetime.now(timezone.utc),
                "validation_status": validated_data.get("status"),
            },
        )
        log_event(
            logger,
            logging.INFO,
            event="context.pipeline.completed",
            stage="pipeline",
            context_id=context_id,
            correlation_id=_get_correlation_id(validated_data, context_id),
            result="success",
            validation_status=validated_data.get("status"),
        )
        return _pipeline_success(
            stage="completed",
            validated_data=validated_data,
            persistence=persistence_result,
        )
    except PipelineStepError as exc:
        _upsert_pipeline_diagnostic(
            correlation_id=exc.correlation_id or correlation_id,
            context_id=context_id,
            status="failed",
            last_error={
                "stage": exc.stage,
                "error_type": exc.error_type,
                "error_code": exc.error_code,
            },
            completed=True,
            hop={
                "service": "context-agent",
                "stage": exc.stage,
                "operation": "generate_full_policy_pipeline",
                "outcome": "failure",
                "completed_at": datetime.now(timezone.utc),
                "error_type": exc.error_type,
                "error_code": exc.error_code,
            },
        )
        log_event(
            logger,
            logging.WARNING,
            event="context.pipeline.completed",
            stage=exc.stage,
            context_id=context_id,
            correlation_id=exc.correlation_id or _get_correlation_id(context_id=context_id),
            result="failure",
            error_code=exc.error_code,
            error_type=exc.error_type,
        )
        return _pipeline_error(exc)
    except Exception:
        logger.exception("Unexpected pipeline failure for context_id=%s", context_id)
        return _pipeline_error(
            PipelineStepError(
                stage="pipeline",
                message="Policy pipeline failed.",
                error_type="internal_error",
                error_code="policy_pipeline_unexpected_failure",
                status_code=500,
                details={"context_id": context_id},
                correlation_id=_get_correlation_id(context_id=context_id),
            )
        )


def render_markdown(text):
    """Render markdown text as HTML for context-detail display."""
    return markdown(text or "", extensions=["fenced_code", "tables", "nl2br"])
