from bson import ObjectId
from uuid import UUID

from test_base import *
import app.routes.routes as routes_module


class FakeCursor:
    def sort(self, *args, **kwargs):
        return self

    def skip(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return []


class FakeContextsCollection:
    def count_documents(self, query):
        return 0

    def find(self, query, fields):
        return FakeCursor()


class FakeDB:
    def __init__(self):
        self.contexts = FakeContextsCollection()


def test_dashboard_route(client, monkeypatch):
    monkeypatch.setattr(routes_module.mongo, "db", FakeDB(), raising=False)

    response = client.get('/')
    assert response.status_code == 200
    assert b"Generated contexts" in response.data

def test_create_route_get(client):
    response = client.get('/create')
    assert response.status_code == 200
    assert b"Create a new context" in response.data


def test_health_route_returns_lightweight_ok_payload(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "context-agent",
    }


def test_ready_route_returns_ok_when_service_is_ready(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "get_readiness_status",
        lambda: {
            "status": "ready",
            "service": "context-agent",
            "checks": {
                "config": {"status": "ok", "missing": []},
                "mongo": {"status": "ok"},
            },
        },
    )

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert response.get_json()["checks"]["mongo"]["status"] == "ok"


def test_ready_route_returns_503_when_service_is_not_ready(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "get_readiness_status",
        lambda: {
            "status": "not_ready",
            "service": "context-agent",
            "checks": {
                "config": {"status": "error", "missing": ["MONGO_URI"]},
                "mongo": {"status": "error", "message": "mongo unavailable"},
            },
        },
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "not_ready",
        "service": "context-agent",
        "checks": {
            "config": {"status": "error", "missing": ["MONGO_URI"]},
            "mongo": {"status": "error", "message": "mongo unavailable"},
        },
    }


def test_send_policy_to_context_returns_400_when_required_fields_missing(client):
    context_id = str(ObjectId())

    response = client.post(
        f"/context/{context_id}/policy",
        json={"policy_text": "Validated policy text"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "validated_policy_missing_fields",
        "message": "Validated policy payload is incomplete.",
        "details": {
            "context_id": context_id,
            "missing_fields": ["generated_at", "policy_agent_version", "language"],
        },
        "correlation_id": response.headers["X-Correlation-ID"],
    }
    UUID(response.headers["X-Correlation-ID"])


def test_send_policy_to_context_preserves_inbound_correlation_id_in_error_body_and_header(client):
    context_id = str(ObjectId())

    response = client.post(
        f"/context/{context_id}/policy",
        json={"policy_text": "Validated policy text"},
        headers={"X-Correlation-ID": "corr-inbound"},
    )

    assert response.status_code == 400
    assert response.headers["X-Correlation-ID"] == "corr-inbound"
    assert response.get_json()["correlation_id"] == "corr-inbound"


def test_send_policy_to_context_redirects_after_storage(client, monkeypatch):
    context_id = str(ObjectId())
    captured = {}
    payload = {
        "policy_text": "Validated policy text",
        "generated_at": "2026-04-10T10:00:00+00:00",
        "policy_agent_version": "0.1.0",
        "language": "en",
        "status": "accepted",
        "recommendations": ["Keep evidence"],
    }

    def fake_store_validated_policy(current_context_id, current_payload):
        captured["context_id"] = current_context_id
        captured["payload"] = current_payload
        return {"context_id": current_context_id}

    monkeypatch.setattr(routes_module, "store_validated_policy", fake_store_validated_policy)

    response = client.post(f"/context/{context_id}/policy", json=payload)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    assert response.headers["X-Correlation-ID"]
    assert captured == {"context_id": context_id, "payload": payload}


def test_trigger_policy_generation_redirects_with_success_flash(client, monkeypatch):
    context_id = str(ObjectId())
    monkeypatch.setattr(
        routes_module,
        "generate_full_policy_pipeline",
        lambda current_context_id: {"success": True, "stage": "completed"},
    )

    response = client.post(f"/context/{context_id}/generate_policy", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("success", "Policy successfully generated and validated.") in flashes


def test_trigger_policy_generation_redirects_with_stage_flash_on_failure(client, monkeypatch):
    context_id = str(ObjectId())
    monkeypatch.setattr(
        routes_module,
        "generate_full_policy_pipeline",
        lambda current_context_id: {
            "success": False,
            "stage": "validation",
            "message": "Policy validation failed.",
        },
    )

    response = client.post(f"/context/{context_id}/generate_policy", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("danger", "validation: Policy validation failed.") in flashes


def test_dashboard_route_adds_security_headers(client, monkeypatch):
    monkeypatch.setattr(routes_module.mongo, "db", FakeDB(), raising=False)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Correlation-ID"]
