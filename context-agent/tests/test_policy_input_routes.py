"""Authenticated Context API tests for opt-in PolicyRequest 1.1 review."""

from copy import deepcopy

import pytest
from bson import ObjectId

import app.routes.routes as routes
from app.services.logic import policy_handoff_context_from_context_record
from test_policy_input import EXAMPLES, example_answers, structured_answers, synthetic_handoff


@pytest.fixture
def context_id(client, monkeypatch):
    identifier = ObjectId()
    handoff = synthetic_handoff()
    monkeypatch.setattr(routes, "policy_handoff_context_from_context_record", lambda _context: deepcopy(handoff))
    routes.mongo.db.contexts.insert_one({
        "_id": identifier,
        "status": "context_ready_for_policy",
        "context_intelligence_plan": {
            "status": "approved", "approved_revision_id": "synthetic-plan-001",
        },
        "final_context": {"status": "ready", "context_ready_for_policy": True},
        "security_context": {"version": "1.0"},
    })
    return identifier


def _url(context_id):
    return f"/context/{context_id}/policy-input"


def test_opt_in_answers_approval_invalidation_and_generation_gate(client, context_id, monkeypatch):
    base = _url(context_id)
    initial = client.get(base)
    assert initial.status_code == 200
    assert initial.get_json()["revision"] == 0
    assert initial.get_json()["approval_status"] == "draft"
    assert "policy_input" not in routes.mongo.db.contexts.find_one({"_id": context_id})

    first = client.post(base + "/answers", json={
        "expected_revision": 0,
        "answers": {"policy_intent.policy_type": {"value": "Synthetic access", "confidence": "confirmed"}},
    })
    assert first.status_code == 200
    assert first.get_json()["revision"] == 1
    assert first.get_json()["material_questions"]
    assert client.post(base + "/approve", json={"expected_revision": 1}).status_code == 409

    answers = structured_answers(example_answers(EXAMPLES[0]))
    second = client.post(base + "/answers", json={"expected_revision": 1, "answers": answers})
    assert second.status_code == 200
    assert second.get_json()["material_questions"] == []
    approved = client.post(base + "/approve", json={"expected_revision": 2})
    assert approved.status_code == 200
    assert approved.get_json()["generation_available"] is False
    state = routes.mongo.db.contexts.find_one({"_id": context_id})["policy_input"]
    assert state["approval"]["answer_snapshot"] == state["revisions"][-1]["answers"]
    assert state["approval"]["request"]["approved_context"]["snapshot_hash"] == approved.get_json()["snapshot_hash"]
    assert client.post(base + "/approve", json={"expected_revision": 2}).status_code == 409
    assert client.get(base).get_json()["approval_status"] == "approved"

    monkeypatch.setattr(routes, "get_system_status", lambda: {"status": "ready"})
    generation = client.post(f"/context/{context_id}/generate_policy", headers={"Accept": "application/json"})
    assert generation.status_code == 409
    assert generation.get_json()["error_code"] == "policy_request_ingress_not_available"

    edit = client.post(base + "/answers", json={
        "expected_revision": 2,
        "answers": {"business_facts.business_priorities": {
            "value": ["Changed priority"], "confidence": "confirmed",
        }},
    })
    assert edit.status_code == 200
    state = routes.mongo.db.contexts.find_one({"_id": context_id})["policy_input"]
    assert state["approval"] is None
    assert len(state["approvals"]) == 1
    assert state["approvals"][0]["request"]["business_facts"]["business_priorities"]["value"] != ["Changed priority"]
    assert client.get(base).get_json()["approval_status"] == "draft"
    generation = client.post(f"/context/{context_id}/generate_policy", headers={"Accept": "application/json"})
    assert generation.status_code == 409
    assert generation.get_json()["error_code"] == "policy_input_not_approved"


def test_stale_revision_invalid_input_and_tenant_boundary(client, context_id):
    base = _url(context_id)
    assert client.post(base + "/answers", json={"expected_revision": 0, "answers": {"bad": {"value": "x", "confidence": "confirmed"}}}).status_code == 400
    for invalid_confidence in ([], {}):
        response = client.post(base + "/answers", json={
            "expected_revision": 0,
            "answers": {"policy_intent.policy_type": {"value": "X", "confidence": invalid_confidence}},
        })
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "invalid_confidence"
        assert "policy_input" not in routes.mongo.db.contexts.find_one({"_id": context_id})
    assert client.post(base + "/answers", json={"expected_revision": 0, "answers": {"policy_intent.policy_type": {"value": "X", "confidence": "confirmed"}}}).status_code == 200
    assert client.post(base + "/answers", json={"expected_revision": 0, "answers": {"policy_intent.policy_type": {"value": "Y", "confidence": "confirmed"}}}).status_code == 409
    assert client.post(base + "/answers", json={"expected_revision": True, "answers": {"policy_intent.policy_type": {"value": "Y", "confidence": "confirmed"}}}).status_code == 400
    foreign = ObjectId()
    routes.mongo.db.contexts.insert_one({"_id": foreign, "organization_id": "another-tenant"})
    assert client.get(_url(foreign)).status_code == 404
    assert client.post(_url(foreign) + "/approve", json={"expected_revision": 1}).status_code == 404


def test_context_fact_conflict_blocks_http_approval(client, context_id, monkeypatch):
    base = _url(context_id)
    answers = structured_answers(example_answers(EXAMPLES[0]))
    assert client.post(base + "/answers", json={
        "expected_revision": 0, "answers": answers,
    }).status_code == 200
    monkeypatch.setattr(
        routes, "policy_handoff_context_from_context_record",
        lambda _context: synthetic_handoff(country="France"),
    )
    response = client.post(base + "/approve", json={"expected_revision": 1})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "context_fact_conflict"
    assert response.get_json()["details"]["field"] == "business_facts.entity_scope.jurisdictions"
    assert routes.mongo.db.contexts.find_one({"_id": context_id})["policy_input"]["approval"] is None


def test_full_instrument_missing_applicability_facts_stays_unapproved(client, context_id):
    base = _url(context_id)
    answers = structured_answers(example_answers(EXAMPLES[0]))
    answers["policy_intent.coverage_mode"] = {"value": "full_instrument", "confidence": "confirmed"}
    answers["policy_intent.requested_instruments"] = {
        "value": [{"id": "synthetic-standard", "version": "v1"}], "confidence": "confirmed",
    }
    answers.pop("business_facts.entity_scope.services")
    response = client.post(base + "/answers", json={"expected_revision": 0, "answers": answers})
    assert response.status_code == 200
    assert {question["field"] for question in response.get_json()["material_questions"]} == {
        "business_facts.entity_scope.services", "business_facts.entity_scope.data_categories",
    }
    approval = client.post(base + "/approve", json={"expected_revision": 1})
    assert approval.status_code == 409
    assert approval.get_json()["error_code"] == "material_questions_open"
    assert routes.mongo.db.contexts.find_one({"_id": context_id})["policy_input"]["approval"] is None


def test_approval_cas_rejects_concurrent_final_context_edit(client, context_id, monkeypatch):
    base = _url(context_id)
    answers = structured_answers(example_answers(EXAMPLES[0]))
    assert client.post(base + "/answers", json={"expected_revision": 0, "answers": answers}).status_code == 200
    collection = routes.mongo.db.contexts
    original_update = collection.update_one

    def concurrent_update(query, update, *args, **kwargs):
        if "final_context" in query:
            original_update({"_id": context_id}, {"$set": {"final_context.status": "changed"}})
        return original_update(query, update, *args, **kwargs)

    monkeypatch.setattr(collection, "update_one", concurrent_update)
    response = client.post(base + "/approve", json={"expected_revision": 1})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "stale_policy_input_revision"
    state = collection.find_one({"_id": context_id})["policy_input"]
    assert state["approval"] is None


def test_v0_context_does_not_activate_policy_input_gate(client, context_id, monkeypatch):
    monkeypatch.setattr(routes, "get_system_status", lambda: {"status": "ready"})
    monkeypatch.setattr(routes, "find_active_pipeline_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "create_pipeline_job", lambda **_kwargs: {"job_id": "synthetic-job", "status": "queued", "current_stage": "queued"})
    monkeypatch.setattr(routes, "start_pipeline_job_worker", lambda *_args: None)
    response = client.post(f"/context/{context_id}/generate_policy", headers={"Accept": "application/json"})
    assert response.status_code != 409 or response.get_json().get("error_code") not in {
        "policy_input_not_approved", "policy_request_ingress_not_available",
    }


def test_real_context_handoff_approval_and_stale_final_context(client):
    identifier = ObjectId()
    security_context = routes.build_context_security_context({
        "country": "Spain", "sector": "Education and language training",
        "need": "Prepare a security policy",
    })
    security_context["analysis"]["missing_information"] = []
    security_context["retrieval_hints"]["collection_families"] = ["controls"]
    context = {
        "_id": identifier,
        "status": "context_ready_for_policy",
        "country": "Spain",
        "sector": "Education and language training",
        "need": "Prepare a security policy",
        "security_context": security_context,
        "context_intelligence_plan": {
            "status": "approved", "approved_revision_id": "synthetic-plan-001",
        },
        "final_context": {
            "version": "1.0", "status": "ready", "context_ready_for_policy": True,
            "plan_revision_id": "synthetic-plan-001", "context_snapshot_hash": "a" * 64,
            "sections": {
                "profile": {"status": "accepted", "content": "Synthetic enterprise profile"},
                "task_findings": {
                    "status": "accepted", "content": "Synthetic controls assessment",
                    "items": [{
                        "item_id": "synthetic-task-001", "status": "completed",
                        "content": "Synthetic control gap",
                        "findings": ["Review access rights"],
                    }],
                },
            },
        },
    }
    routes.mongo.db.contexts.insert_one(context)
    answers = structured_answers(example_answers(EXAMPLES[0]))
    base = _url(identifier)
    assert client.post(base + "/answers", json={
        "expected_revision": 0, "answers": answers,
    }).status_code == 200
    response = client.post(base + "/approve", json={"expected_revision": 1})
    assert response.status_code == 200, response.get_json()
    approved = client.get(base).get_json()
    handoff = policy_handoff_context_from_context_record(
        routes.mongo.db.contexts.find_one({"_id": identifier})
    )
    assert approved["approved_request"]["approved_context"]["policy_handoff_context"] == handoff
    assert approved["approved_request"]["approved_context"]["snapshot_hash"] == response.get_json()["snapshot_hash"]

    routes.mongo.db.contexts.update_one({"_id": identifier}, {
        "$set": {"final_context.sections.profile.content": "Changed synthetic profile"},
    })
    stale = client.get(base).get_json()
    assert stale["approval_status"] == "stale"
    assert stale["approved_request"] is None
    generation = client.post(f"/context/{identifier}/generate_policy", headers={"Accept": "application/json"})
    assert generation.status_code == 409
    assert generation.get_json()["error_code"] == "policy_input_not_approved"


def test_malformed_real_handoff_returns_bounded_error(client):
    identifier = ObjectId()
    routes.mongo.db.contexts.insert_one({
        "_id": identifier,
        "context_intelligence_plan": {
            "status": "approved", "approved_revision_id": "synthetic-plan-001",
        },
        "security_context": {"version": "1.0", "retrieval_hints": {"collection_families": ["controls"]}},
        "final_context": {
            "version": "1.0", "status": "ready", "context_ready_for_policy": True,
            "plan_revision_id": "synthetic-plan-001", "sections": {},
        },
    })
    base = _url(identifier)
    answers = structured_answers(example_answers(EXAMPLES[0]))
    assert client.post(base + "/answers", json={
        "expected_revision": 0, "answers": answers,
    }).status_code == 200
    response = client.post(base + "/approve", json={"expected_revision": 1})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "handoff_not_ready"
    assert "Synthetic" not in str(response.get_json())
