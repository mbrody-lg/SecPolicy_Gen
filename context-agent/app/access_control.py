"""Provider-neutral organization membership and permission decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import g, jsonify, request
from pymongo import ReturnDocument

from app import mongo


ROLE_PERMISSIONS = {
    "viewer": frozenset({"contexts:read", "system:read"}),
    "operator": frozenset(
        {
            "contexts:read",
            "contexts:create",
            "contexts:update",
            "contexts:execute",
            "system:read",
        }
    ),
    "admin": frozenset(
        {
            "contexts:read",
            "contexts:create",
            "contexts:update",
            "contexts:execute",
            "contexts:delete",
            "system:read",
            "diagnostics:read",
            "runtime:refresh",
            "memberships:manage",
        }
    ),
}

PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS = frozenset(
    {
        "identity.login",
        "identity.callback",
        "identity.logout",
        "main.health",
        "main.ready",
        "main.metrics",
        "main.send_policy_to_context",
        "static",
    }
)

ROUTE_PERMISSIONS = {
    ("GET", "/"): "contexts:read",
    ("GET", "/create"): "contexts:create",
    ("POST", "/create"): "contexts:create",
    ("GET", "/system/status"): "system:read",
    ("POST", "/system/refresh"): "runtime:refresh",
    ("GET", "/context/<context_id>"): "contexts:read",
    ("GET", "/context/<context_id>/security_context"): "contexts:read",
    ("GET", "/context/<context_id>/context-plan"): "contexts:read",
    ("POST", "/context/<context_id>/context-building/answers"): "contexts:update",
    ("POST", "/context/<context_id>/context-building/questions/defer"): "contexts:update",
    ("POST", "/context/<context_id>/continue"): "contexts:update",
    ("POST", "/context/<context_id>/context-plan/approve"): "contexts:update",
    ("POST", "/context/<context_id>/context-plan/execute"): "contexts:execute",
    ("POST", "/context/<context_id>/final-context/synthesize"): "contexts:execute",
    ("POST", "/context/<context_id>/final-context/sections/improve"): "contexts:update",
    ("POST", "/context/<context_id>/final-context/sections/regenerate"): "contexts:execute",
    ("GET", "/context/<context_id>/context-lessons/export"): "contexts:read",
    ("POST", "/context/<context_id>/context-lessons/<lesson_id>/status"): "contexts:update",
    ("POST", "/context/<context_id>/delete"): "contexts:delete",
    ("POST", "/context/<context_id>/policy"): "workload:callback",
    ("POST", "/context/<context_id>/generate_policy"): "contexts:execute",
    ("POST", "/context/<context_id>/system/refresh"): "runtime:refresh",
    ("GET", "/pipeline/jobs/<job_id>"): "contexts:read",
    ("GET", "/pipeline/jobs/<job_id>/events"): "contexts:read",
    ("GET", "/context/<context_id>/pipeline/jobs/active"): "contexts:read",
    ("GET", "/diagnostics/<correlation_id>"): "diagnostics:read",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_access_indexes() -> None:
    """Create the small identity uniqueness contract idempotently."""
    mongo.db.principals.create_index([("issuer", 1), ("subject", 1)], unique=True)
    mongo.db.organizations.create_index("organization_id", unique=True)
    mongo.db.memberships.create_index(
        [("principal_id", 1), ("organization_id", 1)],
        unique=True,
    )


def sync_principal(*, issuer: str, subject: str) -> dict:
    """Synchronize an authenticated OIDC principal without importing provider roles."""
    ensure_access_indexes()
    now = _now()
    principal = mongo.db.principals.find_one_and_update(
        {"issuer": issuer, "subject": subject},
        {
            "$set": {"last_login_at": now, "updated_at": now},
            "$setOnInsert": {"_id": str(uuid4()), "status": "active", "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if principal["status"] != "active":
        raise PermissionError("principal_disabled")
    return principal


def provision_organization(*, name: str, organization_id: str | None = None) -> dict:
    """Create or update an organization through an administrative boundary."""
    ensure_access_indexes()
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Organization name must not be empty.")
    resolved_id = organization_id or str(uuid4())
    now = _now()
    return mongo.db.organizations.find_one_and_update(
        {"organization_id": resolved_id},
        {
            "$set": {"name": normalized_name, "status": "active", "updated_at": now},
            "$setOnInsert": {"_id": resolved_id, "organization_id": resolved_id, "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def provision_membership(
    *,
    principal_id: str,
    organization_id: str,
    roles: list[str] | tuple[str, ...],
    is_default: bool = False,
) -> dict:
    """Provision an explicit application membership with allowlisted roles."""
    normalized_roles = sorted(set(roles))
    if not normalized_roles or any(role not in ROLE_PERMISSIONS for role in normalized_roles):
        raise ValueError("Membership roles must be a non-empty subset of admin, operator, viewer.")
    ensure_access_indexes()
    if not mongo.db.principals.find_one({"_id": principal_id, "status": "active"}):
        raise ValueError("Membership principal must exist and be active.")
    if not mongo.db.organizations.find_one({"organization_id": organization_id, "status": "active"}):
        raise ValueError("Membership organization must exist and be active.")
    now = _now()
    if is_default:
        mongo.db.memberships.update_many(
            {"principal_id": principal_id, "organization_id": {"$ne": organization_id}},
            {"$set": {"is_default": False, "updated_at": now}},
        )
    return mongo.db.memberships.find_one_and_update(
        {"principal_id": principal_id, "organization_id": organization_id},
        {
            "$set": {
                "roles": normalized_roles,
                "status": "active",
                "is_default": bool(is_default),
                "updated_at": now,
            },
            "$setOnInsert": {"_id": str(uuid4()), "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def resolve_access_context(*, issuer: str, subject: str, organization_id: str | None = None) -> dict | None:
    """Resolve one active membership and derive permissions from local roles."""
    principal = mongo.db.principals.find_one({"issuer": issuer, "subject": subject, "status": "active"})
    if not principal:
        return None
    query = {"principal_id": principal["_id"], "status": "active"}
    if organization_id:
        query["organization_id"] = organization_id
    memberships = list(mongo.db.memberships.find(query).sort([("is_default", -1), ("created_at", 1)]))
    if not memberships:
        return None
    default_memberships = [membership for membership in memberships if membership.get("is_default")]
    if organization_id:
        membership = memberships[0]
    elif len(default_memberships) == 1:
        membership = default_memberships[0]
    elif len(memberships) == 1:
        membership = memberships[0]
    else:
        return None
    organization = mongo.db.organizations.find_one(
        {"organization_id": membership["organization_id"], "status": "active"}
    )
    if not organization:
        return None
    permissions = sorted(
        set().union(*(ROLE_PERMISSIONS[role] for role in membership.get("roles", []) if role in ROLE_PERMISSIONS))
    )
    return {
        "principal_id": principal["_id"],
        "organization_id": organization["organization_id"],
        "organization_name": organization["name"],
        "roles": membership["roles"],
        "permissions": permissions,
    }


def required_permission() -> str | None:
    """Return the explicit permission for the current route and method."""
    if request.endpoint in PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS:
        return None
    rule = request.url_rule.rule if request.url_rule else ""
    return ROUTE_PERMISSIONS.get((request.method, rule))


def authorize_principal_membership():
    """Resolve membership on every request and fail closed on missing permissions."""
    if request.endpoint in PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS:
        return None
    principal = getattr(g, "principal", None)
    if not principal:
        return None
    access = resolve_access_context(
        issuer=principal["issuer"],
        subject=principal["subject"],
    )
    if not access:
        return jsonify({"success": False, "error_code": "membership_required"}), 403
    permission = required_permission()
    if permission is None:
        return jsonify({"success": False, "error_code": "access_policy_undefined"}), 500
    if permission not in access["permissions"]:
        return jsonify({"success": False, "error_code": "permission_denied"}), 403
    g.access = access
    g.organization_id = access["organization_id"]
    return None
