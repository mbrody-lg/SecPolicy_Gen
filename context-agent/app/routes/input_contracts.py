"""Shared HTTP input validation helpers for Context Agent routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from flask import jsonify


MAX_DETAIL_VALUE_LENGTH = 120
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
PIPELINE_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LESSON_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class RouteInputError(Exception):
    """Bounded contract error raised when route input is malformed."""

    field: str
    error_code: str
    message: str
    status_code: int = 400
    value: Any | None = None


def route_input_error_response(error: RouteInputError):
    """Return a bounded JSON contract-error response."""
    details = {"field": error.field}
    if error.value is not None:
        details[error.field] = _bounded_detail_value(error.value)
    return jsonify({
        "success": False,
        "error_type": "contract_error",
        "error_code": error.error_code,
        "message": error.message,
        "details": details,
    }), error.status_code


def parse_object_id(value: Any, *, field: str = "context_id") -> ObjectId:
    """Parse a Mongo ObjectId from a route parameter."""
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise RouteInputError(
            field=field,
            error_code=f"invalid_{field}",
            message=f"Invalid {field} format.",
            value=value,
        ) from None


def parse_page(value: Any, *, default: int = 1, max_value: int = 1000) -> int:
    """Parse a positive page query parameter."""
    if value in (None, ""):
        return default
    try:
        page = int(str(value))
    except (TypeError, ValueError):
        raise RouteInputError(
            field="page",
            error_code="invalid_page",
            message="Page must be a positive integer.",
            value=value,
        ) from None
    if page < 1 or page > max_value:
        raise RouteInputError(
            field="page",
            error_code="invalid_page",
            message="Page must be a positive integer.",
            value=value,
        )
    return page


def parse_enum(value: Any, *, field: str, allowed: set[str], default: str | None = None) -> str:
    """Parse an allowlisted string value."""
    if value in (None, "") and default is not None:
        return default
    if not isinstance(value, str):
        raise RouteInputError(
            field=field,
            error_code=f"invalid_{field}",
            message=f"{field} is invalid.",
            value=value,
        )
    normalized = value.strip()
    if normalized not in allowed:
        raise RouteInputError(
            field=field,
            error_code=f"invalid_{field}",
            message=f"{field} is invalid.",
            value=value,
        )
    return normalized


def parse_bounded_token(
    value: Any,
    *,
    field: str,
    pattern: re.Pattern[str],
    error_code: str | None = None,
) -> str:
    """Parse a short URL-safe token-like route value."""
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise RouteInputError(
            field=field,
            error_code=error_code or f"invalid_{field}",
            message=f"{field} is invalid.",
            value=value,
        )
    return value.strip()


def require_json_object(value: Any, *, field: str = "body") -> dict:
    """Require a JSON object payload."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RouteInputError(
            field=field,
            error_code=f"invalid_{field}",
            message=f"{field} must be a JSON object.",
        )
    return value


def _bounded_detail_value(value: Any) -> str:
    rendered = str(value)
    if len(rendered) > MAX_DETAIL_VALUE_LENGTH:
        return f"{rendered[:MAX_DETAIL_VALUE_LENGTH]}..."
    return rendered
