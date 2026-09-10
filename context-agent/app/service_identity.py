"""Workload identity boundary for internal Context Agent callbacks."""

from __future__ import annotations

from hmac import compare_digest

from bson import ObjectId
from flask import current_app, g, jsonify, request

from app import mongo


WORKLOAD_ENDPOINTS = frozenset({"main.send_policy_to_context"})


def require_workload_identity():
    """Authenticate the policy callback and bind its persisted organization."""
    if request.endpoint not in WORKLOAD_ENDPOINTS:
        return None

    authorization = request.headers.get("Authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    expected = current_app.config["POLICY_CALLBACK_TOKEN"]
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not credential
        or len(credential) > 4096
        or not compare_digest(credential, expected)
    ):
        response = jsonify({"success": False, "error_code": "workload_authentication_required"})
        response.headers["WWW-Authenticate"] = "Bearer"
        return response, 401

    try:
        context_id = ObjectId((request.view_args or {}).get("context_id"))
    except Exception:
        return jsonify({"success": False, "error_code": "resource_not_found"}), 404
    context = mongo.db.contexts.find_one({"_id": context_id})
    organization_id = (context or {}).get("organization_id")
    if not organization_id:
        return jsonify({"success": False, "error_code": "resource_not_found"}), 404

    g.organization_id = organization_id
    g.workload_principal = {"service": "policy-agent", "authentication": "bearer"}
    return None
