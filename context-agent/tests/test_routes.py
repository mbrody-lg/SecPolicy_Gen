from bson import ObjectId

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


def test_send_policy_to_context_returns_400_when_required_fields_missing(client):
    context_id = str(ObjectId())

    response = client.post(
        f"/context/{context_id}/policy",
        json={"policy_text": "Validated policy text"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Missing required fields: generated_at, policy_agent_version, language"
    }


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
    assert captured == {"context_id": context_id, "payload": payload}
