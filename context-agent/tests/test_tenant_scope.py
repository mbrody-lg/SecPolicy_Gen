from datetime import datetime, timezone

from bson import ObjectId
from flask import g

from app import mongo
from app.tenant_scope import tenant_document, tenant_query


def test_tenant_helpers_override_caller_supplied_owner(app):
    with app.test_request_context("/"):
        g.organization_id = "organization-a"

        assert tenant_query({"organization_id": "organization-b", "status": "ready"}) == {
            "organization_id": "organization-a",
            "status": "ready",
        }
        assert tenant_document({"organization_id": "organization-b", "value": 1}) == {
            "organization_id": "organization-a",
            "value": 1,
        }


def test_cross_tenant_context_is_concealed(client):
    context_id = ObjectId()
    mongo.db.contexts.insert_one({
        "_id": context_id,
        "organization_id": "another-organization",
    })

    response = client.get(f"/context/{context_id}", headers={"Accept": "application/json"})

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "resource_not_found"


def test_cross_tenant_context_cannot_be_deleted(client):
    context_id = ObjectId()
    mongo.db.contexts.insert_one({
        "_id": context_id,
        "organization_id": "another-organization",
    })

    response = client.post(
        f"/context/{context_id}/delete",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "resource_not_found"
    assert mongo.db.contexts.count_documents({"_id": context_id}) == 1


def test_dashboard_lists_only_active_tenant_contexts(client):
    own_context_id = ObjectId()
    other_context_id = ObjectId()
    now = datetime.now(timezone.utc)
    mongo.db.contexts.insert_many([
        {
            "_id": own_context_id,
            "organization_id": "test-organization",
            "created_at": now,
            "status": "planning",
        },
        {
            "_id": other_context_id,
            "organization_id": "another-organization",
            "created_at": now,
            "status": "planning",
        },
    ])

    response = client.get("/")

    assert response.status_code == 200
    assert str(own_context_id).encode() in response.data
    assert str(other_context_id).encode() not in response.data


def test_legacy_context_without_owner_is_concealed(client):
    context_id = ObjectId()
    mongo.db.contexts.insert_one({"_id": context_id})
    mongo.db.contexts.update_one(
        {"_id": context_id},
        {"$unset": {"organization_id": ""}},
    )

    response = client.get(f"/context/{context_id}", headers={"Accept": "application/json"})

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "resource_not_found"


def test_cross_tenant_job_and_diagnostic_are_concealed(client):
    mongo.db.pipeline_jobs.insert_one({
        "job_id": "job-other-tenant",
        "organization_id": "another-organization",
    })
    mongo.db.pipeline_diagnostics.insert_one({
        "correlation_id": "corr-other-tenant",
        "organization_id": "another-organization",
    })

    job_response = client.get("/pipeline/jobs/job-other-tenant")
    diagnostic_response = client.get("/diagnostics/corr-other-tenant")

    assert job_response.status_code == 404
    assert job_response.get_json()["error_code"] == "resource_not_found"
    assert diagnostic_response.status_code == 404
    assert diagnostic_response.get_json()["error_code"] == "resource_not_found"
