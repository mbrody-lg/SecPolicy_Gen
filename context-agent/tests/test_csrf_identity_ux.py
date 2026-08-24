import re

import app.routes.routes as routes_module


def _csrf_token(client) -> str:
    response = client.get("/")
    match = re.search(rb'<meta name="csrf-token" content="([^"]+)">', response.data)
    assert match
    return match.group(1).decode()


def test_navigation_shows_local_identity_and_organization(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get("/")

    assert b"test-operator" in response.data
    assert b"Test Organization" in response.data
    assert b"admin" in response.data
    assert b"Sign out" in response.data


def test_logout_requires_valid_csrf_token(client):
    client.application.config["WTF_CSRF_ENABLED"] = True
    token = _csrf_token(client)

    rejected = client.post("/auth/logout", headers={"Accept": "application/json"})
    accepted = client.post("/auth/logout", data={"csrf_token": token})

    assert rejected.status_code == 400
    assert rejected.get_json()["error_code"] == "csrf_validation_failed"
    assert accepted.status_code == 302
    with client.session_transaction() as session:
        assert "principal" not in session


def test_json_mutation_accepts_csrf_header(client, monkeypatch):
    client.application.config["WTF_CSRF_ENABLED"] = True
    token = _csrf_token(client)
    monkeypatch.setattr(
        routes_module,
        "refresh_system_state",
        lambda: {"success": True, "status": {"status": "ready"}},
    )

    rejected = client.post(
        "/system/refresh",
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    accepted = client.post(
        "/system/refresh",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": token,
        },
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 202
