"""Verified workload identity boundary for Validator Agent mutations."""

from __future__ import annotations

from flask import current_app, g, jsonify, request

from app import mongo
from app.workload_token import (
    ForbiddenWorkloadToken,
    InvalidWorkloadToken,
    WorkloadReplay,
    WorkloadReplayStoreUnavailable,
    consume_token,
    verify_token,
)


ROUTE_SCOPES = {
    "routes.validate_policy": "policy:validate",
    "routes.validate_candidate_policy": "policy:candidate:validate",
}
CALLER_SCOPES = {
    "context-agent": frozenset({"policy:validate"}),
    "docker-agent": frozenset({"policy:candidate:validate"}),
}


def _error(status: int, code: str):
    response = jsonify({"success": False, "error_code": code})
    if status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response, status


def require_service_identity():
    """Only a signed, scoped, tenant-bound one-use token can reach validation."""
    scope = ROUTE_SCOPES.get(request.endpoint)
    if scope is None:
        return None

    scheme, separator, credential = request.headers.get("Authorization", "").partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return _error(401, "service_authentication_required")
    try:
        claims = verify_token(
            credential,
            caller_keys=current_app.config["WORKLOAD_CALLER_KEYS"],
            allowed_scopes=CALLER_SCOPES,
            audience="validator-agent",
            scope=scope,
            method=request.method,
            path=request.path,
        )
    except InvalidWorkloadToken:
        return _error(401, "service_authentication_required")
    except ForbiddenWorkloadToken:
        return _error(403, "service_authorization_forbidden")

    claimed_tenant_header = request.headers.get("X-Tenant-ID")
    if claimed_tenant_header is not None and claimed_tenant_header.strip() != claims["tenant_id"]:
        return _error(403, "service_tenant_forbidden")
    if request.endpoint == "routes.validate_candidate_policy" and not claimed_tenant_header:
        return _error(400, "candidate_metadata_invalid")
    try:
        consume_token(mongo.db, credential, claims)
    except WorkloadReplay:
        return _error(401, "service_authentication_required")
    except WorkloadReplayStoreUnavailable:
        return _error(503, "service_authentication_unavailable")

    g.service_principal = {
        "identity": claims["sub"],
        "authentication": "signed_workload_token",
        "audience": claims["aud"],
        "scopes": claims["scopes"],
        "tenant_id": claims["tenant_id"],
    }
    if request.endpoint == "routes.validate_candidate_policy":
        g.candidate_deadline_enforced = True
    return None
