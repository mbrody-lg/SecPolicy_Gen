"""Organization membership and centralized permission regression tests."""

import pytest

from app import mongo
from app.access_control import (
    PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS,
    ROLE_PERMISSIONS,
    ROUTE_PERMISSIONS,
    provision_membership,
    provision_organization,
    resolve_access_context,
    sync_principal,
)


ISSUER = "https://identity.test/tenant/secpolicygen"


@pytest.fixture(autouse=True)
def clear_access_records(app):
    with app.app_context():
        mongo.db.principals.delete_many({})
        mongo.db.organizations.delete_many({})
        mongo.db.memberships.delete_many({})
        yield


def _provision_access(*, subject="user-1", roles=("viewer",), organization_id="org-1"):
    principal = sync_principal(issuer=ISSUER, subject=subject)
    organization = provision_organization(organization_id=organization_id, name="Example Organization")
    membership = provision_membership(
        principal_id=principal["_id"],
        organization_id=organization["organization_id"],
        roles=roles,
        is_default=True,
    )
    return principal, organization, membership


def test_principal_sync_is_idempotent_and_ignores_provider_roles(app):
    with app.app_context():
        first = sync_principal(issuer=ISSUER, subject="user-1")
        second = sync_principal(issuer=ISSUER, subject="user-1")

        assert first["_id"] == second["_id"]
        assert set(second) >= {"issuer", "subject", "status", "last_login_at"}
        assert "roles" not in second


@pytest.mark.parametrize("role", sorted(ROLE_PERMISSIONS))
def test_membership_derives_only_allowlisted_role_permissions(app, role):
    with app.app_context():
        _provision_access(roles=(role,))

        access = resolve_access_context(issuer=ISSUER, subject="user-1")

        assert access["roles"] == [role]
        assert set(access["permissions"]) == set(ROLE_PERMISSIONS[role])


def test_unknown_role_is_rejected(app):
    with app.app_context():
        principal = sync_principal(issuer=ISSUER, subject="user-1")
        organization = provision_organization(organization_id="org-1", name="Example")

        with pytest.raises(ValueError, match="subset"):
            provision_membership(
                principal_id=principal["_id"],
                organization_id=organization["organization_id"],
                roles=["provider-admin"],
            )


def test_authenticated_principal_without_membership_has_no_access(app):
    with app.app_context():
        sync_principal(issuer=ISSUER, subject="user-1")

        assert resolve_access_context(issuer=ISSUER, subject="user-1") is None


def test_disabled_principal_is_not_reactivated_by_login_sync(app):
    with app.app_context():
        principal = sync_principal(issuer=ISSUER, subject="user-1")
        mongo.db.principals.update_one({"_id": principal["_id"]}, {"$set": {"status": "disabled"}})

        with pytest.raises(PermissionError, match="principal_disabled"):
            sync_principal(issuer=ISSUER, subject="user-1")

        assert mongo.db.principals.find_one({"_id": principal["_id"]})["status"] == "disabled"


def test_multiple_memberships_require_one_explicit_default(app):
    with app.app_context():
        principal, _, _ = _provision_access(organization_id="org-1")
        second = provision_organization(organization_id="org-2", name="Second")
        provision_membership(
            principal_id=principal["_id"],
            organization_id=second["organization_id"],
            roles=["viewer"],
        )
        mongo.db.memberships.update_many({"principal_id": principal["_id"]}, {"$set": {"is_default": False}})

        assert resolve_access_context(issuer=ISSUER, subject="user-1") is None


def test_default_membership_is_unique_per_principal(app):
    with app.app_context():
        principal, _, _ = _provision_access(organization_id="org-1")
        second = provision_organization(organization_id="org-2", name="Second")
        provision_membership(
            principal_id=principal["_id"],
            organization_id=second["organization_id"],
            roles=["operator"],
            is_default=True,
        )

        defaults = list(mongo.db.memberships.find({"principal_id": principal["_id"], "is_default": True}))
        assert [membership["organization_id"] for membership in defaults] == ["org-2"]


def test_viewer_cannot_mutate_contexts(app, monkeypatch):
    monkeypatch.setattr(
        "app.access_control.resolve_access_context",
        lambda **principal: {
            "principal_id": "principal-1",
            "organization_id": "org-1",
            "organization_name": "Example",
            "roles": ["viewer"],
            "permissions": sorted(ROLE_PERMISSIONS["viewer"]),
        },
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["principal"] = {"issuer": ISSUER, "subject": "user-1"}

    response = client.post("/create", data={})

    assert response.status_code == 403
    assert response.get_json()["error_code"] == "permission_denied"


def test_authenticated_principal_without_membership_gets_403(app, monkeypatch):
    monkeypatch.setattr("app.access_control.resolve_access_context", lambda **principal: None)
    client = app.test_client()
    with client.session_transaction() as session:
        session["principal"] = {"issuer": ISSUER, "subject": "user-1"}

    response = client.get("/system/status", headers={"X-Requested-With": "XMLHttpRequest"})

    assert response.status_code == 403
    assert response.get_json()["error_code"] == "membership_required"


def test_human_principal_cannot_use_workload_callback(app, monkeypatch):
    monkeypatch.setattr(
        "app.access_control.resolve_access_context",
        lambda **principal: {
            "principal_id": "principal-1",
            "organization_id": "org-1",
            "organization_name": "Example",
            "roles": ["admin"],
            "permissions": sorted(ROLE_PERMISSIONS["admin"]),
        },
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["principal"] = {"issuer": ISSUER, "subject": "user-1"}

    response = client.post("/context/507f1f77bcf86cd799439011/policy", json={"policy": "test"})

    assert response.status_code == 403
    assert response.get_json()["error_code"] == "permission_denied"


def test_every_protected_route_has_an_explicit_permission(app):
    protected_routes = {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        if rule.endpoint not in PUBLIC_OR_MEMBERSHIP_OPTIONAL_ENDPOINTS
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }

    assert set(ROUTE_PERMISSIONS) == protected_routes
