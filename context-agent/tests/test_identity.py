"""Regression tests for provider-neutral human authentication."""

import app.identity as identity_module
from authlib.integrations.base_client.errors import OAuthError
import pytest
from pymongo.errors import ServerSelectionTimeoutError


@pytest.fixture(autouse=True)
def isolate_access_persistence(monkeypatch):
    monkeypatch.setattr("app.access_control.sync_principal", lambda **principal: principal)
    monkeypatch.setattr(
        "app.access_control.resolve_access_context",
        lambda **principal: {
            "principal_id": "test-principal",
            "organization_id": "test-organization",
            "organization_name": "Test Organization",
            "roles": ["admin"],
            "permissions": [
                "contexts:delete",
                "contexts:create",
                "contexts:execute",
                "contexts:read",
                "contexts:update",
                "diagnostics:read",
                "memberships:manage",
                "runtime:refresh",
                "system:read",
            ],
        },
    )


def test_health_and_ready_remain_public(app):
    client = app.test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code in {200, 503}


def test_unauthenticated_html_request_redirects_without_exposing_contexts(app):
    client = app.test_client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/login?")
    assert b"security_context" not in response.data


def test_unauthenticated_json_request_returns_bounded_401(app):
    response = app.test_client().get(
        "/system/status",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 401
    assert response.get_json() == {
        "success": False,
        "error_code": "authentication_required",
    }


def test_login_rejects_external_post_auth_redirect(app, monkeypatch):
    captured = {}

    def fake_authorize_redirect(redirect_uri):
        captured["redirect_uri"] = redirect_uri
        return "provider-redirect", 302

    monkeypatch.setattr(identity_module.oauth.oidc, "authorize_redirect", fake_authorize_redirect)
    client = app.test_client()

    response = client.get("/auth/login?next=https://attacker.example/collect")

    assert response.status_code == 302
    assert captured["redirect_uri"] == app.config["OIDC_REDIRECT_URI"]
    with client.session_transaction() as session:
        assert session["post_auth_redirect"] == "/"


def test_callback_stores_minimal_principal_without_provider_tokens(app, monkeypatch):
    monkeypatch.setattr(
        identity_module.oauth.oidc,
        "authorize_access_token",
        lambda: {
            "access_token": "must-not-enter-session",
            "refresh_token": "must-not-enter-session",
            "userinfo": {
                "iss": app.config["OIDC_ISSUER_URL"],
                "sub": "user-123",
                "email": "analyst@example.test",
                "name": "Security Analyst",
                "groups": ["provider-specific-group"],
            },
        },
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["post_auth_redirect"] = "/context/example"

    response = client.get("/auth/callback", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/context/example"
    with client.session_transaction() as session:
        assert session["principal"] == {
            "issuer": app.config["OIDC_ISSUER_URL"],
            "subject": "user-123",
        }
        serialized = repr(dict(session))
        assert "access_token" not in serialized
        assert "refresh_token" not in serialized
        assert "provider-specific-group" not in serialized


def test_callback_rejects_identity_without_subject(app, monkeypatch):
    monkeypatch.setattr(
        identity_module.oauth.oidc,
        "authorize_access_token",
        lambda: {
            "userinfo": {
                "iss": app.config["OIDC_ISSUER_URL"],
                "email": "missing-sub@example.test",
            }
        },
    )

    response = app.test_client().get("/auth/callback")

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "invalid_identity"


def test_callback_rejects_identity_from_another_issuer(app, monkeypatch):
    monkeypatch.setattr(
        identity_module.oauth.oidc,
        "authorize_access_token",
        lambda: {"userinfo": {"iss": "https://attacker.example", "sub": "user-123"}},
    )

    response = app.test_client().get("/auth/callback")

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "invalid_identity"


def test_callback_clears_session_when_principal_is_disabled(app, monkeypatch):
    monkeypatch.setattr(
        identity_module.oauth.oidc,
        "authorize_access_token",
        lambda: {"userinfo": {"iss": app.config["OIDC_ISSUER_URL"], "sub": "disabled-user"}},
    )
    monkeypatch.setattr(
        "app.access_control.sync_principal",
        lambda **principal: (_ for _ in ()).throw(PermissionError("principal_disabled")),
    )
    client = app.test_client()

    response = client.get("/auth/callback")

    assert response.status_code == 403
    assert response.get_json()["error_code"] == "principal_disabled"
    with client.session_transaction() as session:
        assert not session


def test_callback_clears_session_when_identity_store_is_unavailable(app, monkeypatch):
    monkeypatch.setattr(
        identity_module.oauth.oidc,
        "authorize_access_token",
        lambda: {"userinfo": {"iss": app.config["OIDC_ISSUER_URL"], "sub": "user-1"}},
    )
    monkeypatch.setattr(
        "app.access_control.sync_principal",
        lambda **principal: (_ for _ in ()).throw(ServerSelectionTimeoutError("unavailable")),
    )
    client = app.test_client()

    response = client.get("/auth/callback")

    assert response.status_code == 503
    assert response.get_json()["error_code"] == "identity_store_unavailable"
    with client.session_transaction() as session:
        assert not session


def test_callback_returns_bounded_error_and_clears_session_on_provider_failure(app, monkeypatch):
    monkeypatch.setattr(
        identity_module.oauth.oidc,
        "authorize_access_token",
        lambda: (_ for _ in ()).throw(OAuthError(error="invalid_grant")),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["post_auth_redirect"] = "/context/example"

    response = client.get("/auth/callback")

    assert response.status_code == 401
    assert response.get_json() == {
        "success": False,
        "error_code": "authentication_failed",
    }
    with client.session_transaction() as session:
        assert not session


def test_authenticated_session_preserves_existing_route_behavior(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["principal"] = {
            "issuer": app.config["OIDC_ISSUER_URL"],
            "subject": "user-123",
        }

    response = client.get("/create")

    assert response.status_code == 200


def test_logout_clears_authenticated_session(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["principal"] = {
            "issuer": app.config["OIDC_ISSUER_URL"],
            "subject": "user-123",
        }

    response = client.post("/auth/logout", follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "principal" not in session


def test_service_callback_is_fail_closed_without_workload_identity(app):
    response = app.test_client().post(
        "/context/507f1f77bcf86cd799439011/policy",
        json={"policy": "untrusted"},
    )

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "workload_authentication_required"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_service_callback_rejects_invalid_workload_credential(app):
    response = app.test_client().post(
        "/context/507f1f77bcf86cd799439011/policy",
        json={"policy": "untrusted"},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "workload_authentication_required"


def test_service_callback_authenticates_before_concealing_missing_resource(app):
    response = app.test_client().post(
        "/context/507f1f77bcf86cd799439011/policy",
        json={"policy": "test"},
        headers={"Authorization": "Bearer test-only-policy-callback-token"},
    )

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "resource_not_found"


def test_oidc_client_uses_discovery_pkce_and_openid_scope(app):
    assert identity_module.oauth.oidc._server_metadata_url == (
        f"{app.config['OIDC_ISSUER_URL']}/.well-known/openid-configuration"
    )
    assert identity_module.oauth.oidc.client_kwargs["code_challenge_method"] == "S256"
    assert "openid" in identity_module.oauth.oidc.client_kwargs["scope"].split()


def test_oidc_client_can_use_a_provider_specific_ca_bundle(app, tmp_path, monkeypatch):
    ca_bundle = tmp_path / "provider-ca.crt"
    ca_bundle.write_text("test-ca", encoding="utf-8")
    app.config["OIDC_CA_BUNDLE"] = str(ca_bundle)
    registered = {}
    monkeypatch.setattr(identity_module.oauth, "register", lambda **kwargs: registered.update(kwargs))

    identity_module.init_identity(app)

    assert registered["client_kwargs"]["verify"] == str(ca_bundle)
