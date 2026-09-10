"""Reverse PoC for the identity and tenant-isolation advisory gate."""

from bson import ObjectId

from app import mongo


def _persistence_counts():
    return {
        name: getattr(mongo.db, name).count_documents({})
        for name in ("contexts", "interactions", "pipeline_jobs", "pipeline_events")
    }


def test_unauthenticated_operations_return_401_without_side_effects(app):
    context_id = ObjectId()
    mongo.db.contexts.insert_one(
        {"_id": context_id, "organization_id": "victim-organization", "name": "private"}
    )
    before = _persistence_counts()
    client = app.test_client()
    headers = {"X-Requested-With": "XMLHttpRequest"}

    responses = [
        client.get("/", headers=headers),
        client.get(f"/context/{context_id}", headers=headers),
        client.post("/create", json={"name": "injected"}, headers=headers),
        client.post(f"/context/{context_id}/delete", json={}, headers=headers),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert all(response.get_json()["error_code"] == "authentication_required" for response in responses)
    assert _persistence_counts() == before


def test_principal_without_membership_cannot_enumerate_or_mutate(app):
    context_id = ObjectId()
    mongo.db.contexts.insert_one(
        {"_id": context_id, "organization_id": "victim-organization", "name": "private"}
    )
    before = _persistence_counts()
    client = app.test_client()
    with client.session_transaction() as session:
        session["principal"] = {
            "issuer": app.config["OIDC_ISSUER_URL"],
            "subject": "principal-without-membership",
        }

    read_response = client.get(f"/context/{context_id}", headers={"Accept": "application/json"})
    delete_response = client.post(f"/context/{context_id}/delete", json={})

    assert read_response.status_code == 403
    assert delete_response.status_code == 403
    assert _persistence_counts() == before


def test_cross_tenant_delete_is_concealed_without_side_effects(client):
    context_id = ObjectId()
    mongo.db.contexts.insert_one(
        {"_id": context_id, "organization_id": "victim-organization", "name": "private"}
    )
    before = _persistence_counts()

    response = client.post(f"/context/{context_id}/delete", json={})

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "resource_not_found"
    assert _persistence_counts() == before
