"""Small structured logging helpers for policy-agent."""

import json
import logging

from app import get_request_correlation_id

SERVICE_NAME = "policy-agent"


def build_log_event(
    *,
    event: str,
    stage: str,
    context_id: str | None = None,
    correlation_id: str | None = None,
    **fields,
) -> str:
    """Build a compact JSON log line with stable observability keys."""
    payload = {
        "event": event,
        "service": SERVICE_NAME,
        "stage": stage,
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
