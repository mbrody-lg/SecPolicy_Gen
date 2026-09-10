"""Tenant ownership helpers for organization-scoped resources."""

from __future__ import annotations

from bson import ObjectId
from flask import g, jsonify, request

from app import mongo
from app.access_control import PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS, required_permission


def ensure_tenant_indexes() -> None:
    """Create organization-first indexes for tenant-owned collections."""
    mongo.db.contexts.create_index([("organization_id", 1), ("created_at", -1)])
    mongo.db.interactions.create_index([("organization_id", 1), ("context_id", 1)])
    mongo.db.pipeline_jobs.create_index([("organization_id", 1), ("job_id", 1)], unique=True)
    mongo.db.pipeline_jobs.create_index(
        [("organization_id", 1), ("context_id", 1), ("command", 1), ("created_at", -1)]
    )
    mongo.db.pipeline_events.create_index([("organization_id", 1), ("job_id", 1), ("created_at", -1)])
    mongo.db.pipeline_diagnostics.create_index(
        [("organization_id", 1), ("correlation_id", 1)], unique=True
    )


def tenant_query(query: dict | None = None) -> dict:
    """Bind a Mongo query to the organization resolved for this request."""
    organization_id = getattr(g, "organization_id", None)
    if not organization_id:
        raise RuntimeError("organization_context_required")
    scoped = dict(query or {})
    scoped["organization_id"] = organization_id
    return scoped


def tenant_document(document: dict) -> dict:
    """Bind a new Mongo document to the organization resolved for this request."""
    scoped = dict(document)
    scoped["organization_id"] = tenant_query()["organization_id"]
    return scoped


def authorize_tenant_resource():
    """Conceal organization-owned resources outside the active tenant."""
    if request.endpoint in PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS:
        return None
    if required_permission() == "workload:callback":
        return None
    organization_id = getattr(g, "organization_id", None)
    if not organization_id:
        return None

    view_args = request.view_args or {}
    context_id = view_args.get("context_id")
    if context_id:
        try:
            object_id = ObjectId(context_id)
        except Exception:
            return None
        resource = mongo.db.contexts.find_one({"_id": object_id})
        if resource and resource.get("organization_id") != organization_id:
            return _not_found()

    job_id = view_args.get("job_id")
    job = mongo.db.pipeline_jobs.find_one({"job_id": job_id}) if job_id else None
    if job and job.get("organization_id") != organization_id:
        return _not_found()

    correlation_id = view_args.get("correlation_id")
    diagnostic = (
        mongo.db.pipeline_diagnostics.find_one({"correlation_id": correlation_id})
        if correlation_id
        else None
    )
    if diagnostic and diagnostic.get("organization_id") != organization_id:
        return _not_found()
    return None


def _not_found():
    return jsonify({"success": False, "error_code": "resource_not_found"}), 404
