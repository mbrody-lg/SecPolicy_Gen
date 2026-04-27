"""Service helpers for policy-agent configuration, validation, and execution flow."""

import logging
import os
from datetime import datetime, timezone

import yaml
from flask import current_app

from app import CORRELATION_ID_HEADER, get_request_correlation_id, mongo
from app.agents.factory import create_agent_from_config
from app.observability import build_log_event, log_event
from app.rag.context import build_retrieval_context
from app.rag.planner import build_retrieval_plan
from app.rag.sources import load_rag_source_manifest


POLICY_GENERATION_REQUIRED_FIELDS = ["context_id", "refined_prompt", "language", "model_version"]
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
MAX_CONTEXT_ID_LENGTH = 128
MAX_LANGUAGE_LENGTH = 16
MAX_MODEL_VERSION_LENGTH = 64
MAX_POLICY_AGENT_VERSION_LENGTH = 64
MAX_GENERATED_AT_LENGTH = 64
MAX_STATUS_LENGTH = 32
MAX_PROMPT_LENGTH = 20000
MAX_BUSINESS_CONTEXT_FIELDS = 32
MAX_BUSINESS_CONTEXT_VALUE_LENGTH = 4000
MAX_BUSINESS_CONTEXT_LIST_ITEMS = 50
MAX_BUSINESS_CONTEXT_LIST_ITEM_LENGTH = 1000
MAX_POLICY_TEXT_LENGTH = 50000
MAX_FEEDBACK_ITEMS = 20
MAX_FEEDBACK_ITEM_LENGTH = 1000

logger = logging.getLogger(__name__)
SERVICE_NAME = "policy-agent"


class PipelineStepError(Exception):
    """Structured policy-agent error used to keep failures explicit and stable."""

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


def _get_correlation_id(payload: dict | None) -> str | None:
    header_correlation_id = get_request_correlation_id()
    if not isinstance(payload, dict):
        return header_correlation_id
    return header_correlation_id or payload.get("correlation_id") or payload.get("context_id")


def _apply_correlation_id_to_agent(agent, correlation_id: str | None) -> None:
    """Attach request correlation headers to outbound OpenAI SDK calls when supported."""
    if not correlation_id:
        return

    openai_wrapper = getattr(agent, "client", None)
    sdk_client = getattr(openai_wrapper, "client", None)
    if sdk_client is None:
        return

    header_value = {CORRELATION_ID_HEADER: correlation_id}
    with_options = getattr(sdk_client, "with_options", None)
    if callable(with_options):
        configured_client = with_options(default_headers=header_value)
        openai_wrapper.client = configured_client
        if hasattr(openai_wrapper, "chat"):
            openai_wrapper.chat = configured_client.chat
        return

    existing_headers = getattr(sdk_client, "_default_headers", None)
    if isinstance(existing_headers, dict):
        sdk_client._default_headers = existing_headers | header_value
        return

    existing_headers = getattr(sdk_client, "default_headers", None)
    if isinstance(existing_headers, dict):
        sdk_client.default_headers = existing_headers | header_value


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


def _missing_fields(payload: dict, required_fields: list[str]) -> list[str]:
    return [field for field in required_fields if field not in payload]


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


def _require_string_list(
    payload: dict,
    *,
    field: str,
    max_items: int,
    max_item_length: int,
    correlation_id: str | None,
) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise PipelineStepError(
            stage="contract_validation",
            message=f"Field '{field}' must be a list of strings.",
            error_type="contract_error",
            error_code="invalid_field_type",
            status_code=400,
            details={"field": field, "expected_type": "list[string]"},
            correlation_id=correlation_id,
        )

    if len(value) > max_items:
        raise PipelineStepError(
            stage="contract_validation",
            message=f"Field '{field}' exceeds the allowed item count.",
            error_type="contract_error",
            error_code="field_too_large",
            status_code=413,
            details={"field": field, "max_items": max_items},
            correlation_id=correlation_id,
        )

    normalized_items = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise PipelineStepError(
                stage="contract_validation",
                message=f"Field '{field}' must contain only strings.",
                error_type="contract_error",
                error_code="invalid_field_type",
                status_code=400,
                details={"field": field, "index": index, "expected_type": "string"},
                correlation_id=correlation_id,
            )

        normalized_item = item.strip()
        if not normalized_item:
            raise PipelineStepError(
                stage="contract_validation",
                message=f"Field '{field}' contains an empty item.",
                error_type="contract_error",
                error_code="empty_required_field",
                status_code=400,
                details={"field": field, "index": index},
                correlation_id=correlation_id,
            )

        if len(normalized_item) > max_item_length:
            raise PipelineStepError(
                stage="contract_validation",
                message=f"Field '{field}' contains an oversized item.",
                error_type="contract_error",
                error_code="field_too_large",
                status_code=413,
                details={
                    "field": field,
                    "index": index,
                    "max_length": max_item_length,
                },
                correlation_id=correlation_id,
            )
        normalized_items.append(normalized_item)

    return normalized_items


def load_policy_config() -> dict:
    """Load policy-agent YAML configuration from configured path."""
    config_path = current_app.config["CONFIG_PATH"]

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def get_health_status() -> dict:
    """Return a lightweight liveness payload without touching external services."""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
    }


def _collect_chroma_vector_entries(config: dict) -> list[dict]:
    """Extract configured Chroma vector entries from role definitions."""
    entries: list[dict] = []
    roles = config.get("roles", [])
    if not isinstance(roles, list):
        return entries

    for role in roles:
        if not isinstance(role, dict):
            continue
        vector_entries = role.get("vector", [])
        if not isinstance(vector_entries, list):
            continue
        for vector_entry in vector_entries:
            if not isinstance(vector_entry, dict):
                continue
            chroma_entry = vector_entry.get("chroma")
            if isinstance(chroma_entry, dict):
                entries.append(chroma_entry)
            elif "chroma" in vector_entry:
                entries.append(vector_entry)

    return entries


def _validate_readiness_config(config: dict) -> None:
    """Validate the minimal configuration shape required for safe startup."""
    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a mapping.")

    missing_keys = [key for key in ("type", "name", "model", "roles") if key not in config]
    if missing_keys:
        raise ValueError(f"Configuration missing required keys: {', '.join(missing_keys)}")

    if not isinstance(config.get("roles"), list):
        raise ValueError("Configuration field 'roles' must be a list.")


def get_readiness_status() -> tuple[dict, int]:
    """Run minimal safe readiness checks for config and critical dependencies."""
    checks: dict[str, dict] = {}
    ready = True
    config = None

    config_path = current_app.config["CONFIG_PATH"]
    try:
        config = load_policy_config()
        _validate_readiness_config(config)
        checks["config"] = {
            "status": "ok",
            "source": "loaded",
        }
    except FileNotFoundError:
        ready = False
        checks["config"] = {
            "status": "error",
            "reason": "not_found",
        }
    except yaml.YAMLError:
        ready = False
        checks["config"] = {
            "status": "error",
            "reason": "invalid_yaml",
        }
    except Exception:
        ready = False
        checks["config"] = {
            "status": "error",
            "reason": "invalid_config",
        }

    try:
        mongo.cx.admin.command("ping")
        checks["mongo"] = {"status": "ok"}
    except Exception:
        ready = False
        checks["mongo"] = {
            "status": "error",
            "reason": "ping_failed",
        }

    chroma_entries = _collect_chroma_vector_entries(config or {})
    if chroma_entries:
        chroma_port = os.getenv("CHROMA_PORT", "8000")
        try:
            chroma_port_value = int(chroma_port)
            first_entry = chroma_entries[0]
            collections = first_entry.get("collection", [])
            if not isinstance(collections, list) or not collections:
                raise ValueError("Configured Chroma collections must be a non-empty list.")
            checks["chroma"] = {
                "status": "configured",
                "mode": "config_only",
                "collection_count": len(collections),
            }
        except Exception:
            ready = False
            checks["chroma"] = {
                "status": "error",
                "mode": "config_only",
                "reason": "invalid_configuration",
            }
    else:
        checks["chroma"] = {
            "status": "skipped",
            "reason": "not_configured",
        }

    if ready:
        return {
            "status": "ready",
            "service": SERVICE_NAME,
            "checks": checks,
        }, 200

    return {
        "status": "not_ready",
        "service": SERVICE_NAME,
        "checks": checks,
    }, 503


def validate_generation_payload(payload: dict | None) -> dict:
    """Validate the generate-policy request contract and normalize fields."""
    correlation_id = _get_correlation_id(payload)
    data = _ensure_payload_object(payload, correlation_id)
    missing = _missing_fields(data, POLICY_GENERATION_REQUIRED_FIELDS)
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

    normalized = {
        "context_id": _require_string_field(
            data,
            field="context_id",
            max_length=MAX_CONTEXT_ID_LENGTH,
            correlation_id=correlation_id,
        ),
        "refined_prompt": _require_string_field(
            data,
            field="refined_prompt",
            max_length=MAX_PROMPT_LENGTH,
            correlation_id=correlation_id,
        ),
        "language": _require_string_field(
            data,
            field="language",
            max_length=MAX_LANGUAGE_LENGTH,
            correlation_id=correlation_id,
        ),
        "model_version": _require_string_field(
            data,
            field="model_version",
            max_length=MAX_MODEL_VERSION_LENGTH,
            correlation_id=correlation_id,
        ),
        "correlation_id": correlation_id,
    }
    if "business_context" in data:
        normalized["business_context"] = _validate_business_context(
            data["business_context"],
            correlation_id=correlation_id,
        )
    return normalized


def _validate_business_context(value: object, *, correlation_id: str | None) -> dict:
    """Validate optional structured context for retrieval planning."""
    if not isinstance(value, dict):
        raise PipelineStepError(
            stage="contract_validation",
            message="Field 'business_context' must be an object.",
            error_type="contract_error",
            error_code="invalid_field_type",
            status_code=400,
            details={"field": "business_context", "expected_type": "object"},
            correlation_id=correlation_id,
        )
    if len(value) > MAX_BUSINESS_CONTEXT_FIELDS:
        raise PipelineStepError(
            stage="contract_validation",
            message="Field 'business_context' exceeds the allowed field count.",
            error_type="contract_error",
            error_code="field_too_large",
            status_code=413,
            details={"field": "business_context", "max_fields": MAX_BUSINESS_CONTEXT_FIELDS},
            correlation_id=correlation_id,
        )

    normalized = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise PipelineStepError(
                stage="contract_validation",
                message="Field 'business_context' contains an invalid key.",
                error_type="contract_error",
                error_code="invalid_field_type",
                status_code=400,
                details={"field": "business_context", "expected_key_type": "string"},
                correlation_id=correlation_id,
            )
        if isinstance(item, str):
            if len(item) > MAX_BUSINESS_CONTEXT_VALUE_LENGTH:
                raise PipelineStepError(
                    stage="contract_validation",
                    message="Field 'business_context' contains an oversized value.",
                    error_type="contract_error",
                    error_code="field_too_large",
                    status_code=413,
                    details={
                        "field": "business_context",
                        "key": key,
                        "max_length": MAX_BUSINESS_CONTEXT_VALUE_LENGTH,
                    },
                    correlation_id=correlation_id,
                )
            normalized[key.strip()] = item.strip()
        elif isinstance(item, list):
            if len(item) > MAX_BUSINESS_CONTEXT_LIST_ITEMS:
                raise PipelineStepError(
                    stage="contract_validation",
                    message="Field 'business_context' contains too many list items.",
                    error_type="contract_error",
                    error_code="field_too_large",
                    status_code=413,
                    details={
                        "field": "business_context",
                        "key": key,
                        "max_items": MAX_BUSINESS_CONTEXT_LIST_ITEMS,
                    },
                    correlation_id=correlation_id,
                )
            normalized[key.strip()] = _validate_business_context_list(
                key=key,
                value=item,
                correlation_id=correlation_id,
            )
        elif item is None:
            normalized[key.strip()] = None
        else:
            raise PipelineStepError(
                stage="contract_validation",
                message="Field 'business_context' contains an unsupported value type.",
                error_type="contract_error",
                error_code="invalid_field_type",
                status_code=400,
                details={"field": "business_context", "key": key, "expected_type": "string|list[string]|null"},
                correlation_id=correlation_id,
            )
    return normalized


def _validate_business_context_list(
    *, key: str, value: list, correlation_id: str | None
) -> list[str]:
    """Validate list-style business context values without silent coercion."""
    normalized = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str):
            raise PipelineStepError(
                stage="contract_validation",
                message="Field 'business_context' list values must be strings.",
                error_type="contract_error",
                error_code="invalid_field_type",
                status_code=400,
                details={
                    "field": "business_context",
                    "key": key,
                    "index": index,
                    "expected_type": "string",
                },
                correlation_id=correlation_id,
            )
        item = entry.strip()
        if len(item) > MAX_BUSINESS_CONTEXT_LIST_ITEM_LENGTH:
            raise PipelineStepError(
                stage="contract_validation",
                message="Field 'business_context' contains an oversized list value.",
                error_type="contract_error",
                error_code="field_too_large",
                status_code=413,
                details={
                    "field": "business_context",
                    "key": key,
                    "index": index,
                    "max_length": MAX_BUSINESS_CONTEXT_LIST_ITEM_LENGTH,
                },
                correlation_id=correlation_id,
            )
        if item:
            normalized.append(item)
    return normalized


def validate_policy_update_payload(payload: dict | None, path_context_id: str) -> tuple[dict, dict]:
    """Validate the policy-update request contract and current persistence state."""
    correlation_id = _get_correlation_id(payload) or str(path_context_id)
    data = _ensure_payload_object(payload, correlation_id)
    missing = _missing_fields(data, POLICY_UPDATE_REQUIRED_FIELDS)
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
        "language": _require_string_field(
            data,
            field="language",
            max_length=MAX_LANGUAGE_LENGTH,
            correlation_id=correlation_id,
        ),
        "policy_text": _require_string_field(
            data,
            field="policy_text",
            max_length=MAX_POLICY_TEXT_LENGTH,
            correlation_id=correlation_id,
        ),
        "policy_agent_version": _require_string_field(
            data,
            field="policy_agent_version",
            max_length=MAX_POLICY_AGENT_VERSION_LENGTH,
            correlation_id=correlation_id,
        ),
        "generated_at": _require_string_field(
            data,
            field="generated_at",
            max_length=MAX_GENERATED_AT_LENGTH,
            correlation_id=correlation_id,
        ),
        "status": _require_string_field(
            data,
            field="status",
            max_length=MAX_STATUS_LENGTH,
            correlation_id=correlation_id,
        ),
        "reasons": _require_string_list(
            data,
            field="reasons",
            max_items=MAX_FEEDBACK_ITEMS,
            max_item_length=MAX_FEEDBACK_ITEM_LENGTH,
            correlation_id=correlation_id,
        ),
        "recommendations": _require_string_list(
            data,
            field="recommendations",
            max_items=MAX_FEEDBACK_ITEMS,
            max_item_length=MAX_FEEDBACK_ITEM_LENGTH,
            correlation_id=correlation_id,
        ),
        "correlation_id": correlation_id,
    }

    if normalized_payload["context_id"] != str(path_context_id):
        raise PipelineStepError(
            stage="contract_validation",
            message="Context ID mismatch.",
            error_type="contract_error",
            error_code="context_id_mismatch",
            status_code=400,
            details={
                "path_context_id": str(path_context_id),
                "payload_context_id": normalized_payload["context_id"],
            },
            correlation_id=correlation_id,
        )

    policy = mongo.db.policies.find_one({"context_id": str(path_context_id)})
    if not policy:
        raise PipelineStepError(
            stage="persistence_lookup",
            message="Policy not found.",
            error_type="validation_error",
            error_code="policy_not_found",
            status_code=404,
            details={"context_id": str(path_context_id)},
            correlation_id=correlation_id,
        )

    return normalized_payload, policy


def _store_policy_config(model_version: str, config: dict) -> None:
    mongo.db.policy_configs.update_one(
        {"model_version": model_version},
        {
            "$set": {
                "model_version": model_version,
                "yaml_content": config,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def run_with_agent(
    refined_prompt: str,
    context_id: str,
    model_version: str,
    business_context: dict | None = None,
) -> dict:
    """Run full policy-agent role pipeline for initial policy generation."""
    config = load_policy_config()
    _store_policy_config(model_version, config)

    agent = create_agent_from_config(config)
    retrieval_plan = build_retrieval_plan(
        build_retrieval_context(
            {
                "context_id": context_id,
                "refined_prompt": refined_prompt,
                "language": business_context.get("language", "") if business_context else "",
                "business_context": business_context or {},
            }
        ),
        load_rag_source_manifest(),
    )
    correlation_id = get_request_correlation_id() or context_id
    _apply_correlation_id_to_agent(agent, correlation_id)
    log_event(
        logger,
        logging.INFO,
        event="policy.pipeline.generation_started",
        stage="policy_generation",
        context_id=context_id,
        correlation_id=correlation_id,
        model_version=model_version,
    )
    return agent.run(prompt=refined_prompt, context_id=context_id, retrieval_plan=retrieval_plan)


def update_with_agent(prompt: str, context_id: str | None = None, model_version: str | None = None) -> dict:
    """Run only update role pipeline to revise an existing policy text."""
    config = load_policy_config()
    agent = create_agent_from_config(config)
    correlation_id = get_request_correlation_id() or context_id
    _apply_correlation_id_to_agent(agent, correlation_id)

    last_role = [agent.roles[-1]]
    agent.roles = last_role

    log_event(
        logger,
        logging.INFO,
        event="policy.pipeline.update_started",
        stage="policy_update",
        context_id=context_id,
        correlation_id=correlation_id,
        model_version=model_version,
        role_count=len(last_role),
    )
    return agent.run(prompt, context_id)


def generate_policy_payload(payload: dict | None) -> dict:
    """Validate payload, run generation flow, and normalize the persisted response."""
    data = validate_generation_payload(payload)
    correlation_id = data["correlation_id"]

    try:
        result_object = run_with_agent(
            refined_prompt=data["refined_prompt"],
            context_id=data["context_id"],
            model_version=data["model_version"],
            business_context={**data.get("business_context", {}), "language": data["language"]},
        )
    except FileNotFoundError as exc:
        logger.exception(
            build_log_event(
                event="policy.pipeline.generation_failed",
                stage="config_loading",
                context_id=data["context_id"],
                correlation_id=correlation_id,
                error_code="policy_config_not_found",
                model_version=data["model_version"],
            )
        )
        raise PipelineStepError(
            stage="config_loading",
            message="Policy-agent configuration is unavailable.",
            error_type="internal_error",
            error_code="policy_config_not_found",
            status_code=500,
            details={"operation": "load_policy_config"},
            correlation_id=correlation_id,
        ) from exc
    except yaml.YAMLError as exc:
        logger.exception(
            build_log_event(
                event="policy.pipeline.generation_failed",
                stage="config_loading",
                context_id=data["context_id"],
                correlation_id=correlation_id,
                error_code="policy_config_invalid",
                model_version=data["model_version"],
            )
        )
        raise PipelineStepError(
            stage="config_loading",
            message="Policy-agent configuration is invalid.",
            error_type="internal_error",
            error_code="policy_config_invalid",
            status_code=500,
            details={"operation": "load_policy_config"},
            correlation_id=correlation_id,
        ) from exc
    except Exception as exc:
        logger.exception(
            build_log_event(
                event="policy.pipeline.generation_failed",
                stage="policy_generation",
                context_id=data["context_id"],
                correlation_id=correlation_id,
                error_code="policy_generation_failed",
                model_version=data["model_version"],
            )
        )
        raise PipelineStepError(
            stage="policy_generation",
            message="Policy generation failed.",
            error_type="internal_error",
            error_code="policy_generation_failed",
            status_code=500,
            details={"operation": "generate_policy"},
            correlation_id=correlation_id,
        ) from exc

    result = {
        "success": True,
        "context_id": data["context_id"],
        "correlation_id": correlation_id,
        "language": data["language"],
        "policy_text": result_object["text"],
        "structured_plan": result_object.get("structured_plan", []),
        "model_version": data["model_version"],
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lifecycle_status": "generated",
        "revision_count": 0,
        "ownership": {
            "owner_service": "policy-agent",
            "source_of_truth": True,
            "collection": "policies",
        },
    }
    mongo.db.policies.insert_one(result)
    log_event(
        logger,
        logging.INFO,
        event="policy.pipeline.generation_completed",
        stage="completed",
        context_id=data["context_id"],
        correlation_id=correlation_id,
        model_version=data["model_version"],
        lifecycle_status=result["lifecycle_status"],
    )
    return _pipeline_success(stage="completed", policy=result)


def run_generation_pipeline(payload: dict | None) -> dict:
    """Execute policy generation and return a structured success or error envelope."""
    try:
        return generate_policy_payload(payload)
    except PipelineStepError as exc:
        return _pipeline_error(exc)


def build_policy_update_prompt(policy_text: str, reasons: list[str], recommendations: list[str]) -> str:
    """Build the deterministic revision prompt sent to the update role."""
    return (
        f"[Original Policy]:\n{policy_text}\n\n"
        f"[Reasons]:\n{yaml.safe_dump(reasons, sort_keys=False)}\n"
        f"[Recommendations]:\n{yaml.safe_dump(recommendations, sort_keys=False)}"
    )


def update_policy_payload(payload: dict | None, path_context_id: str) -> dict:
    """Validate update payload, run revision flow, and normalize the persisted response."""
    data, policy = validate_policy_update_payload(payload, path_context_id)
    correlation_id = data["correlation_id"]
    prompt = build_policy_update_prompt(
        data["policy_text"],
        data["reasons"],
        data["recommendations"],
    )

    try:
        result_object = update_with_agent(
            prompt=prompt,
            context_id=str(path_context_id),
            model_version=policy.get("model_version"),
        )
    except FileNotFoundError as exc:
        logger.exception(
            build_log_event(
                event="policy.pipeline.update_failed",
                stage="config_loading",
                context_id=str(path_context_id),
                correlation_id=correlation_id,
                error_code="policy_config_not_found",
                model_version=policy.get("model_version"),
            )
        )
        raise PipelineStepError(
            stage="config_loading",
            message="Policy-agent configuration is unavailable.",
            error_type="internal_error",
            error_code="policy_config_not_found",
            status_code=500,
            details={"operation": "load_policy_config"},
            correlation_id=correlation_id,
        ) from exc
    except yaml.YAMLError as exc:
        logger.exception(
            build_log_event(
                event="policy.pipeline.update_failed",
                stage="config_loading",
                context_id=str(path_context_id),
                correlation_id=correlation_id,
                error_code="policy_config_invalid",
                model_version=policy.get("model_version"),
            )
        )
        raise PipelineStepError(
            stage="config_loading",
            message="Policy-agent configuration is invalid.",
            error_type="internal_error",
            error_code="policy_config_invalid",
            status_code=500,
            details={"operation": "load_policy_config"},
            correlation_id=correlation_id,
        ) from exc
    except Exception as exc:
        logger.exception(
            build_log_event(
                event="policy.pipeline.update_failed",
                stage="policy_update",
                context_id=str(path_context_id),
                correlation_id=correlation_id,
                error_code="policy_update_failed",
                model_version=policy.get("model_version"),
            )
        )
        raise PipelineStepError(
            stage="policy_update",
            message="Policy update failed.",
            error_type="internal_error",
            error_code="policy_update_failed",
            status_code=500,
            details={"operation": "update_policy"},
            correlation_id=correlation_id,
        ) from exc

    result = {
        "success": True,
        "context_id": data["context_id"],
        "correlation_id": correlation_id,
        "language": data["language"],
        "policy_text": result_object["text"],
        "structured_plan": policy.get("structured_plan", []),
        "model_version": policy.get("model_version"),
        "policy_agent_version": data["policy_agent_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lifecycle_status": "revised",
        "revision_count": policy.get("revision_count", 0) + 1,
        "ownership": policy.get(
            "ownership",
            {
                "owner_service": "policy-agent",
                "source_of_truth": True,
                "collection": "policies",
            },
        ),
        "last_validation_status": data["status"],
        "last_validation_reasons": data["reasons"],
        "last_validation_recommendations": data["recommendations"],
    }

    mongo.db.policies.update_one(
        {"_id": policy["_id"]},
        {
            "$set": {
                "language": result["language"],
                "policy_text": result["policy_text"],
                "structured_plan": result["structured_plan"],
                "model_version": result["model_version"],
                "correlation_id": result["correlation_id"],
                "policy_agent_version": result["policy_agent_version"],
                "generated_at": result["generated_at"],
                "lifecycle_status": result["lifecycle_status"],
                "revision_count": result["revision_count"],
                "ownership": result["ownership"],
                "last_validation_status": result["last_validation_status"],
                "last_validation_reasons": result["last_validation_reasons"],
                "last_validation_recommendations": result["last_validation_recommendations"],
            }
        },
    )

    log_event(
        logger,
        logging.INFO,
        event="policy.pipeline.update_completed",
        stage="completed",
        context_id=data["context_id"],
        correlation_id=correlation_id,
        model_version=policy.get("model_version"),
        lifecycle_status=result["lifecycle_status"],
        revision_count=result["revision_count"],
    )
    return _pipeline_success(stage="completed", policy=result)


def run_policy_update_pipeline(payload: dict | None, path_context_id: str) -> dict:
    """Execute policy update flow and return a structured success or error envelope."""
    try:
        return update_policy_payload(payload, path_context_id)
    except PipelineStepError as exc:
        return _pipeline_error(exc)
