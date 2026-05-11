"""Small structured logging helpers for policy-agent."""

import json
import logging

from app import get_request_correlation_id

SERVICE_NAME = "policy-agent"
REQUIRED_LOG_FIELDS = ("event", "service", "stage", "result")
OPTIONAL_LOG_FIELDS = (
    "correlation_id",
    "context_id",
    "route",
    "method",
    "status_code",
    "result",
    "error_code",
)
NUMERIC_LOG_FIELDS = ("duration_ms", "timeout_seconds", "status_code")


def _derive_result(event: str, status_code: int | None = None) -> str:
    """Derive a bounded result for legacy call sites that do not pass one yet."""
    if event.endswith((".started", ".request", ".received")):
        return "started"
    if event.endswith((".failed", ".persistence_failed")):
        return "failure"
    if event.endswith(".skipped"):
        return "skipped"
    if status_code is not None:
        return "success" if status_code < 400 else "failure"
    if event.endswith((".completed", ".response")):
        return "success"
    return "unknown"


def build_log_event(
    *,
    event: str,
    stage: str,
    result: str | None = None,
    context_id: str | None = None,
    correlation_id: str | None = None,
    **fields,
) -> str:
    """Build a compact JSON log line with stable observability keys."""
    payload = {
        "event": event,
        "service": SERVICE_NAME,
        "stage": stage,
        "result": result or _derive_result(event, fields.get("status_code")),
    }
    resolved_correlation_id = correlation_id or get_request_correlation_id()
    if resolved_correlation_id:
        payload["correlation_id"] = str(resolved_correlation_id)
    if context_id:
        payload["context_id"] = str(context_id)
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    return json.dumps(payload, sort_keys=True, default=str)


def log_event(logger: logging.Logger, level: int, **fields) -> None:
    """Emit a structured log event."""
    logger.log(level, build_log_event(**fields))
