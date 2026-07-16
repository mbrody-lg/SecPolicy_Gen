"""Fail-closed request contract for non-authoritative candidate capabilities."""

import re
from datetime import datetime, timedelta, timezone

from flask import g, request


HEADER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
MAX_DEADLINE = timedelta(minutes=5)
CANDIDATE_MAX_CONTENT_LENGTH = 256 * 1024


def _error(status_code: int, error_code: str, message: str) -> tuple[dict, int]:
    return ({
        "success": False,
        "error_type": "authorization_error" if status_code in {401, 403} else "contract_error",
        "error_code": error_code,
        "message": message,
        "details": {"stage": "candidate_contract"},
    }, status_code)


def _safe_header(name: str, max_length: int = 128) -> str | None:
    value = request.headers.get(name, "").strip()
    if not value or len(value) > max_length or not HEADER_PATTERN.fullmatch(value):
        return None
    return value


def authorize_candidate_request(*, audience: str, scope: str) -> tuple[dict | None, tuple[dict, int] | None]:
    """Authorize a principal verified by the future INIT-11 middleware."""
    request.max_content_length = min(
        request.max_content_length or CANDIDATE_MAX_CONTENT_LENGTH,
        CANDIDATE_MAX_CONTENT_LENGTH,
    )
    if request.content_length and request.content_length > request.max_content_length:
        return None, _error(413, "request_too_large", "Request body exceeds the allowed size.")

    principal = getattr(g, "service_principal", None)
    if not isinstance(principal, dict):
        return None, _error(503, "candidate_identity_unavailable", "Candidate identity is unavailable.")
    identity = principal.get("identity")
    scopes = principal.get("scopes")
    if not isinstance(identity, str) or not identity or not isinstance(scopes, list):
        return None, _error(503, "candidate_identity_unavailable", "Candidate identity is unavailable.")
    if principal.get("audience") != audience:
        return None, _error(403, "candidate_audience_forbidden", "Candidate audience is not allowed.")
    if scope not in scopes:
        return None, _error(403, "candidate_scope_forbidden", "Candidate scope is not allowed.")

    tenant_id = _safe_header("X-Tenant-ID", 64)
    idempotency_key = _safe_header("Idempotency-Key")
    correlation_id = _safe_header("X-Correlation-ID")
    if not tenant_id or not idempotency_key or not correlation_id:
        return None, _error(400, "candidate_metadata_invalid", "Candidate request metadata is invalid.")
    if tenant_id != principal.get("tenant_id"):
        return None, _error(403, "candidate_tenant_forbidden", "Candidate tenant is not allowed.")

    deadline_value = request.headers.get("X-Request-Deadline", "").strip()
    try:
        deadline = datetime.fromisoformat(deadline_value.replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            raise ValueError
        deadline = deadline.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None, _error(400, "candidate_deadline_invalid", "Candidate deadline is invalid.")

    now = datetime.now(timezone.utc)
    if deadline <= now:
        return None, _error(408, "candidate_deadline_expired", "Candidate deadline has expired.")
    if deadline - now > MAX_DEADLINE:
        return None, _error(400, "candidate_deadline_too_far", "Candidate deadline exceeds the allowed window.")
    if getattr(g, "candidate_deadline_enforced", False) is not True:
        return None, _error(503, "candidate_execution_unavailable", "Candidate execution is unavailable.")

    return {
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "deadline": deadline,
    }, None
