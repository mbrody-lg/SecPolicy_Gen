"""Bearer-token identity boundary for internal service requests."""

from __future__ import annotations

from hmac import compare_digest

from flask import current_app, g, jsonify, request


PROTECTED_ENDPOINTS = frozenset({
    "routes.validate_policy",
})


def require_service_identity():
    """Authenticate protected service endpoints with a shared bearer token."""
    if request.endpoint not in PROTECTED_ENDPOINTS:
        return None

    authorization = request.headers.get("Authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    expected = current_app.config["SERVICE_AUTH_TOKEN"]
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not credential
        or len(credential) > 4096
        or not compare_digest(credential, expected)
    ):
        response = jsonify({"success": False, "error_code": "service_authentication_required"})
        response.headers["WWW-Authenticate"] = "Bearer"
        return response, 401

    g.service_principal = {
        "identity": "internal-service",
        "authentication": "bearer",
        "audience": "validator-agent",
    }
    return None
