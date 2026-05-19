import json
import logging

from bson import ObjectId
import pytest
from uuid import UUID

from test_base import *
import app.routes.routes as routes_module


class FakeCursor:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def sort(self, sort_param=None, direction=None, *args, **kwargs):
        if sort_param:
            sort_items = (
                [(sort_param, direction)]
                if isinstance(sort_param, str)
                else sort_param
            )
            for key, direction in reversed(sort_items):
                self.docs.sort(
                    key=lambda doc: doc.get(key),
                    reverse=direction == -1,
                )
        return self

    def skip(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeContextsCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def count_documents(self, query):
        return len(list(self._matching_docs(query)))

    def find(self, query, fields):
        return FakeCursor(self._matching_docs(query))

    def find_one(self, query, sort=None):
        docs = list(self._matching_docs(query))
        if sort:
            for key, direction in reversed(sort):
                docs.sort(
                    key=lambda doc: doc.get(key),
                    reverse=direction == -1,
                )
        return docs[0] if docs else None

    def _matching_docs(self, query):
        for doc in self.docs:
            matches = True
            for key, value in query.items():
                if isinstance(value, dict) and "$in" in value:
                    matches = doc.get(key) in value["$in"]
                else:
                    matches = doc.get(key) == value
                if not matches:
                    break
            if matches:
                yield doc


class FakeInteractionsCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query):
        return FakeCursor(
            doc for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        )


class FakeDB:
    def __init__(self, contexts=None, interactions=None, pipeline_jobs=None):
        self.contexts = FakeContextsCollection(contexts)
        self.interactions = FakeInteractionsCollection(interactions)
        self.pipeline_jobs = FakeContextsCollection(pipeline_jobs)


def test_dashboard_route(client, monkeypatch):
    monkeypatch.setattr(routes_module.mongo, "db", FakeDB(), raising=False)
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get('/')
    assert response.status_code == 200
    assert b"Generated contexts" in response.data


def test_dashboard_route_renders_system_status_panel(client, monkeypatch):
    monkeypatch.setattr(routes_module.mongo, "db", FakeDB(), raising=False)
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {
            "status": "not_ready",
            "services": [
                {"service": "context-agent", "status": "ready", "status_code": 200},
                {"service": "policy-agent", "status": "ready", "status_code": 200},
                {"service": "validator-agent", "status": "ready", "status_code": 200},
            ],
            "rag": {
                "status": "requires_refresh",
                "missing_collections": ["guia"],
                "refresh_job": {
                    "status": "failed",
                    "started_at": "2026-05-15T10:00:00+00:00",
                    "completed_at": "2026-05-15T10:05:00+00:00",
                    "result": {"message": "RAG refresh timed out."},
                },
            },
        },
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Application readiness" in response.data
    assert b"policy-agent RAG" in response.data
    assert b"requires_refresh" in response.data
    assert b"Missing: guia" in response.data
    assert b"RAG refresh timed out." in response.data
    assert b"rag-refresh-started-value" in response.data
    assert b"rag-refresh-id-value" in response.data
    assert b"rag-refresh-correlation-value" in response.data
    assert b"data-system-refresh-button" in response.data
    assert b"Update state" in response.data


def test_dashboard_route_separates_context_status_from_policy_process(client, monkeypatch):
    context_without_job = ObjectId()
    context_with_job = ObjectId()
    context_with_failure = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[
                {
                    "_id": context_without_job,
                    "created_at": "2026-05-15T10:00:00+00:00",
                    "version": 1,
                    "status": "completed",
                    "country": "Spain",
                    "region": "Catalonia",
                    "sector": "Education",
                    "need": "Protect student data.",
                },
                {
                    "_id": context_with_job,
                    "created_at": "2026-05-15T11:00:00+00:00",
                    "version": 1,
                    "status": "completed",
                    "country": "Netherlands",
                    "region": "Europe",
                    "sector": "Technology",
                    "need": "Protect source code.",
                },
                {
                    "_id": context_with_failure,
                    "created_at": "2026-05-15T12:00:00+00:00",
                    "version": 1,
                    "status": "completed",
                    "country": "Germany",
                    "region": "Central Europe",
                    "sector": "Audiovisual",
                    "need": "Protect content.",
                },
            ],
            pipeline_jobs=[
                {
                    "job_id": "job-running",
                    "context_id": str(context_with_job),
                    "command": "generate_policy",
                    "status": "policy_generating",
                    "current_stage": "policy_generation",
                    "created_at": "2026-05-15T11:05:00+00:00",
                },
                {
                    "job_id": "job-failed",
                    "context_id": str(context_with_failure),
                    "command": "generate_policy",
                    "status": "failed",
                    "current_stage": "policy_generation",
                    "created_at": "2026-05-15T12:05:00+00:00",
                    "last_error": {
                        "error_code": "policy_agent_request_failed",
                        "safe_message": "Policy generation failed.",
                    },
                },
            ],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Context: <span class=\"font-semibold\">completed</span>" in response.data
    assert b"Policy process:" in response.data
    assert b"Not started" in response.data
    assert b"Generating policy" in response.data
    assert b"policy_generation" in response.data
    assert b"Failed" in response.data
    assert b"policy_agent_request_failed" in response.data


def test_create_route_get(client):
    response = client.get('/create')
    assert response.status_code == 200
    assert b"Create a new context" in response.data


def test_create_route_persists_security_context(client, monkeypatch):
    captured_prompts = []
    monkeypatch.setattr(
        routes_module,
        "run_with_agent",
        lambda prompt, context_id, model_version=None: captured_prompts.append(prompt) or "Reviewable context plan",
    )

    response = client.post(
        "/create",
        data={
            "country": "Init05Land",
            "region": "Catalonia",
            "sector": "Healthcare",
            "company_activity": "Private outpatient clinic",
            "important_assets": "Medical records",
            "critical_assets": "Patient data",
            "data_categories": "health_data",
            "third_party_dependencies": "external laboratory",
            "current_security_operations": "Backups",
            "methodology": "ISO 27001",
            "generic": "Specific",
            "policy_type": "Access control policy",
            "need": "Protect patient data",
        },
    )

    assert response.status_code == 302
    context = routes_module.mongo.db.contexts.find_one({"country": "Init05Land"})
    assert context["status"] == "awaiting_task_validation"
    assert context["security_context_version"] == routes_module.SECURITY_CONTEXT_VERSION
    assert context["security_context"]["profile"]["sector"] == "Healthcare"
    assert context["security_context"]["profile"]["activity"] == "Private outpatient clinic"
    assert context["security_context"]["policy_intent"]["policy_type"] == "Access control policy"
    assert "external laboratory" in context["security_context"]["information_assets"]["third_party_dependencies"]
    assert context["security_context"]["information_assets"]["data_categories"] == [
        "health_data"
    ]
    assert context["security_context"]["retrieval_hints"]["collection_families"] == [
        "legal_norms",
        "sector_norms",
        "security_frameworks",
        "risk_methodologies",
        "implementation_guides",
    ]
    assert context["context_building"]["status"] == "sufficient"
    assert context["context_building"]["questions"] == []
    assert context["context_intelligence_plan"]["status"] == "draft"
    assert context["context_intelligence_plan"]["tasks"][0]["id"] == "company_profile"
    assert context["context_intelligence_plan"]["tasks"][-1]["id"] == "final_synthesis"
    assert "Produce a reviewable analysis plan" in captured_prompts[0]
    assert "Company profile and operating model" in captured_prompts[0]


def test_create_route_persists_context_building_questions_when_context_is_incomplete(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "run_with_agent",
        lambda prompt, context_id, model_version=None: "Reviewable context plan",
    )

    response = client.post(
        "/create",
        data={
            "country": "Init05IncompleteLand",
            "need": "Build a security plan",
        },
    )

    assert response.status_code == 302
    context = routes_module.mongo.db.contexts.find_one({"country": "Init05IncompleteLand"})
    assert context["status"] == "context_building_needs_input"
    assert context["context_building"]["status"] == "needs_information"
    assert [question["field_path"] for question in context["context_building"]["questions"]] == [
        "profile.sector",
        "information_assets.critical_assets",
    ]


def test_context_building_answers_update_context_and_rebuild_plan(client, monkeypatch):
    context_id = ObjectId()
    security_context = routes_module.build_context_security_context({
        "country": "Spain",
        "need": "Build a security plan",
    })
    context_building = routes_module.build_context_building_state(
        {"country": "Spain", "need": "Build a security plan"},
        security_context=security_context,
    )
    routes_module.mongo.db.contexts.insert_one({
        "_id": context_id,
        "country": "Spain",
        "need": "Build a security plan",
        "status": "context_building_needs_input",
        "security_context": security_context,
        "context_building": context_building,
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.post(
        f"/context/{context_id}/context-building/answers",
        data={
            "question_id": "context_building_profile_sector",
            "answer": "Healthcare",
        },
    )

    assert response.status_code == 302
    context = routes_module.mongo.db.contexts.find_one({"_id": context_id})
    assert context["sector"] == "Healthcare"
    assert context["status"] == "context_building_needs_input"
    assert context["security_context"]["profile"]["sector"] == "Healthcare"
    assert "profile.sector" not in context["context_building"]["missing_information"]
    assert "information_assets.critical_assets" in context["context_building"]["missing_information"]
    interaction = routes_module.mongo.db.interactions.find_one({
        "context_id": context_id,
        "question_id": "context_building_profile_sector",
    })
    assert interaction["answer"] == "Healthcare"


def test_context_building_answers_can_complete_context(client):
    context_id = ObjectId()
    security_context = routes_module.build_context_security_context({
        "country": "Spain",
        "need": "Build a security plan",
    })
    context_building = routes_module.build_context_building_state(
        {"country": "Spain", "need": "Build a security plan"},
        security_context=security_context,
    )
    routes_module.mongo.db.contexts.insert_one({
        "_id": context_id,
        "country": "Spain",
        "need": "Build a security plan",
        "status": "context_building_needs_input",
        "security_context": security_context,
        "context_building": context_building,
    })

    response = client.post(
        f"/context/{context_id}/context-building/answers",
        data={
            "answers[context_building_profile_sector]": "Healthcare",
            "answers[context_building_information_assets_critical_assets]": "Patient records",
        },
    )

    assert response.status_code == 302
    context = routes_module.mongo.db.contexts.find_one({"_id": context_id})
    assert context["status"] == "awaiting_task_validation"
    assert context["context_building"]["status"] == "sufficient"
    assert context["context_intelligence_plan"]["context_snapshot"]["sector"] == "Healthcare"


def test_context_detail_renders_context_intelligence_plan(client, monkeypatch):
    context_id = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[
                {
                    "_id": context_id,
                    "status": "awaiting_task_validation",
                    "context_intelligence_plan": {
                        "version": "1.0",
                        "status": "draft",
                        "review": {"required": True},
                        "tasks": [
                            {
                                "id": "company_profile",
                                "order": 1,
                                "title": "Company profile and operating model",
                                "objective": "Clarify company operations.",
                                "status": "planned",
                            }
                        ],
                    },
                }
            ],
            interactions=[],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Context intelligence plan" in response.data
    assert b"Awaiting validation" in response.data
    assert b"Company profile and operating model" in response.data
    assert b"Approve plan" in response.data


def test_approve_context_plan_updates_status_and_stores_feedback(client, monkeypatch):
    context_id = ObjectId()
    routes_module.mongo.db.contexts.insert_one({
        "_id": context_id,
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.post(
        f"/context/{context_id}/context-plan/approve",
        data={"feedback": "Also cover supplier access."},
    )

    assert response.status_code == 302
    context = routes_module.mongo.db.contexts.find_one({"_id": context_id})
    assert context["status"] == "context_plan_approved"
    assert context["context_intelligence_plan"]["status"] == "approved"
    assert context["context_intelligence_plan"]["review"]["user_feedback"] == (
        "Also cover supplier access."
    )
    assert context["context_intelligence_plan"]["review"]["approval_notes"] == (
        "Also cover supplier access."
    )
    assert context["context_intelligence_plan"]["approved_revision_id"] == "plan-rev-1"
    assert context["context_intelligence_plan"]["revisions"][0]["revision_id"] == "plan-rev-1"
    assert context["context_intelligence_plan"]["revisions"][0]["context_snapshot_hash"]
    assert {task["status"] for task in context["context_intelligence_plan"]["tasks"]} == {
        "approved"
    }
    interaction = routes_module.mongo.db.interactions.find_one({
        "context_id": context_id,
        "question_id": "context_plan_approved",
    })
    assert interaction["answer"] == "Also cover supplier access."


def test_approve_context_plan_blocks_when_context_building_needs_information(client, monkeypatch):
    context_id = ObjectId()
    routes_module.mongo.db.contexts.insert_one({
        "_id": context_id,
        "country": "Spain",
        "need": "Build a security plan",
        "context_building": {
            "version": "1.0",
            "status": "needs_information",
            "questions": [
                {
                    "id": "context_building_profile_sector",
                    "status": "pending",
                    "field_path": "profile.sector",
                }
            ],
        },
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.post(
        f"/context/{context_id}/context-plan/approve",
        data={"feedback": "Looks good."},
    )

    assert response.status_code == 302
    context = routes_module.mongo.db.contexts.find_one({"_id": context_id})
    assert context["context_intelligence_plan"]["status"] == "draft"


def test_trigger_context_plan_execution_starts_job(client, monkeypatch):
    context_id = str(ObjectId())
    _insert_policy_ready_context(context_id)
    captured = {}
    monkeypatch.setattr(
        routes_module,
        "find_active_pipeline_job",
        lambda current_context_id, command="generate_policy": None,
    )

    def fake_create_pipeline_job(**kwargs):
        captured.update(kwargs)
        return {
            "job_id": "job-context-plan",
            "context_id": kwargs["context_id"],
            "correlation_id": "corr-1",
            "command": kwargs["command"],
            "status": "queued",
            "current_stage": "queued",
        }

    monkeypatch.setattr(routes_module, "create_pipeline_job", fake_create_pipeline_job)
    monkeypatch.setattr(
        routes_module,
        "start_pipeline_job_worker",
        lambda job: {"started": True, "job_id": job["job_id"]},
    )

    response = client.post(f"/context/{context_id}/context-plan/execute", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    assert captured["command"] == "execute_context_plan"
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("info", "Context plan execution started. Current stage: queued.") in flashes


def test_trigger_context_plan_execution_blocks_unapproved_plan_json(client, monkeypatch):
    context_id = str(ObjectId())
    routes_module.mongo.db.contexts.insert_one({
        "_id": ObjectId(context_id),
        "context_building": {"status": "sufficient"},
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("job must not be created before plan approval"),
    )

    response = client.post(
        f"/context/{context_id}/context-plan/execute",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "context_plan_not_approved"


def test_trigger_context_plan_execution_reuses_active_job(client, monkeypatch):
    context_id = str(ObjectId())
    _insert_policy_ready_context(context_id)
    monkeypatch.setattr(
        routes_module,
        "find_active_pipeline_job",
        lambda current_context_id, command="generate_policy": {
            "job_id": "job-active",
            "context_id": current_context_id,
            "correlation_id": "corr-active",
            "command": command,
            "status": "context_task_running",
            "current_stage": "context_plan_execution",
        },
    )
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("must not create duplicate context plan job"),
    )

    response = client.post(f"/context/{context_id}/context-plan/execute", follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("info", "Context plan execution is already running.") in flashes


def test_context_plan_route_returns_plan_and_active_revision(client):
    context_id = ObjectId()
    plan = routes_module.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    routes_module.mongo.db.contexts.insert_one({
        "_id": context_id,
        "context_intelligence_plan": plan,
    })

    response = client.get(f"/context/{context_id}/context-plan")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["context_intelligence_plan"]["approved_revision_id"] == "plan-rev-1"
    assert payload["active_revision"]["revision_id"] == "plan-rev-1"


def test_context_detail_renders_approved_plan_revision_metadata(client, monkeypatch):
    context_id = ObjectId()
    plan = routes_module.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[
                {
                    "_id": context_id,
                    "status": "context_plan_approved",
                    "context_intelligence_plan": plan,
                }
            ],
            interactions=[],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Approved revision plan-rev-1" in response.data
    assert b"Snapshot:" in response.data


def test_context_detail_renders_context_plan_execution_panel(client, monkeypatch):
    context_id = ObjectId()
    plan = routes_module.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[
                {
                    "_id": context_id,
                    "status": "context_plan_approved",
                    "context_intelligence_plan": plan,
                }
            ],
            interactions=[],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Context plan execution" in response.data
    assert b"Execute approved plan" in response.data


def test_security_context_route_returns_persisted_context(client):
    context_id = routes_module.mongo.db.contexts.insert_one(
        {
            "country": "France",
            "sector": "E-commerce",
            "critical_assets": "Payment system",
            "need": "Protect sales",
            "security_context_version": "1.0",
            "security_context": {
                "version": "1.0",
                "profile": {
                    "sector": "E-commerce",
                    "activity": None,
                    "size_band": None,
                    "region": None,
                    "operating_countries": ["France"],
                    "languages": ["en"],
                    "business_model": None,
                    "service_type": None,
                },
                "information_assets": {
                    "important_assets": [],
                    "critical_assets": ["Payment system"],
                    "data_categories": ["commerce_data"],
                    "third_party_dependencies": [],
                    "cloud_services": [],
                },
                "compliance": {
                    "jurisdictions": ["France"],
                    "regulatory_hints": [],
                    "methodologies": [],
                },
                "security_posture": {
                    "current_controls": [],
                    "maturity": None,
                    "known_gaps": [],
                    "risk_tolerance": None,
                    "governance_owner": None,
                },
                "policy_intent": {
                    "need": "Protect sales",
                    "policy_type": None,
                    "scope": None,
                    "exclusions": None,
                    "audience": None,
                    "language": "en",
                    "specificity": None,
                },
                "analysis": {
                    "facts": [],
                    "missing_information": [],
                    "confidence": "medium",
                },
                "retrieval_hints": {
                    "collection_families": ["legal_norms"],
                    "jurisdictions": ["France"],
                    "sectors": ["E-commerce"],
                    "data_types": ["commerce_data"],
                    "methodologies": [],
                },
            },
        }
    ).inserted_id

    response = client.get(f"/context/{context_id}/security_context")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["context_id"] == str(context_id)
    assert payload["security_context"]["profile"]["sector"] == "E-commerce"


def test_security_context_route_builds_payload_for_legacy_context(client):
    context_id = routes_module.mongo.db.contexts.insert_one(
        {
            "country": "France",
            "sector": "E-commerce",
            "critical_assets": "Payment system",
            "need": "Protect sales",
        }
    ).inserted_id

    response = client.get(f"/context/{context_id}/security_context")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["security_context"]["profile"]["sector"] == "E-commerce"
    assert payload["security_context"]["retrieval_hints"]["jurisdictions"] == ["France"]


def test_security_context_route_rejects_invalid_context_id(client):
    response = client.get("/context/not-an-object-id/security_context")

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_context_id"


def test_context_detail_renders_security_context_panel(client, monkeypatch):
    context_id = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[
                {
                    "_id": context_id,
                    "status": "completed",
                    "security_context_version": "1.0",
                    "security_context": {
                        "profile": {
                            "sector": "Healthcare",
                            "operating_countries": ["Spain"],
                            "region": "Catalonia",
                        },
                        "information_assets": {
                            "critical_assets": ["Patient data"],
                            "data_categories": ["health_data"],
                            "third_party_dependencies": ["external_service_provider"],
                        },
                        "compliance": {
                            "jurisdictions": ["Spain"],
                            "regulatory_hints": ["gdpr"],
                            "methodologies": ["ISO 27001"],
                        },
                        "analysis": {
                            "missing_information": [],
                            "confidence": "medium",
                        },
                        "retrieval_hints": {
                            "collection_families": ["legal_norms", "sector_norms"],
                        },
                    },
                }
            ],
            interactions=[
                {
                    "context_id": context_id,
                    "origin": "agent",
                    "answer": "Refined context",
                    "timestamp": "2026-05-08T00:00:00+00:00",
                }
            ],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Security context" in response.data
    assert b"Analysis ready" in response.data
    assert b"Healthcare" in response.data
    assert b"health_data" in response.data
    assert b"legal_norms, sector_norms" in response.data
    assert b"Version 1.0" in response.data


def test_context_detail_renders_security_context_missing_information(client, monkeypatch):
    context_id = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[
                {
                    "_id": context_id,
                    "status": "completed",
                    "security_context": {
                        "profile": {
                            "sector": None,
                            "operating_countries": [],
                            "region": None,
                        },
                        "information_assets": {
                            "critical_assets": [],
                            "data_categories": [],
                            "third_party_dependencies": [],
                        },
                        "compliance": {
                            "jurisdictions": [],
                            "regulatory_hints": [],
                            "methodologies": [],
                        },
                        "analysis": {
                            "missing_information": ["profile.sector"],
                            "confidence": "very_low",
                        },
                        "retrieval_hints": {
                            "collection_families": ["legal_norms"],
                        },
                    },
                }
            ],
            interactions=[],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Needs more information" in response.data
    assert b"Missing information" in response.data
    assert b"profile.sector" in response.data


def test_context_detail_renders_security_context_absent_state(client, monkeypatch):
    context_id = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[{"_id": context_id, "status": "completed"}],
            interactions=[],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Security context" in response.data
    assert b"Not available yet" in response.data
    assert b"Structured security analysis is not available" in response.data


def test_context_detail_disables_policy_generation_when_runtime_is_not_ready(client, monkeypatch):
    context_id = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[{"_id": context_id, "status": "completed"}],
            interactions=[
                {
                    "context_id": context_id,
                    "origin": "agent",
                    "answer": "Refined context",
                    "timestamp": "2026-05-08T00:00:00+00:00",
                }
            ],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {
            "status": "not_ready",
            "rag": {
                "status": "requires_refresh",
                "missing_collections": [],
                "refresh_job": {
                    "status": "running",
                    "started_at": "2026-05-15T10:00:00+00:00",
                },
                "embedding_models": [
                    {
                        "model": "intfloat/multilingual-e5-base",
                        "status": "missing",
                        "reason": "not_cached",
                    }
                ],
            },
        },
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Application runtime is not ready" in response.data
    assert b"intfloat/multilingual-e5-base (missing)" in response.data
    assert b"running" in response.data
    assert b"rag-refresh-elapsed-value" in response.data
    assert b"Update state" in response.data
    assert b"disabled" in response.data


def test_context_detail_shows_active_pipeline_job(client, monkeypatch):
    context_id = ObjectId()
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[{"_id": context_id, "status": "completed"}],
            interactions=[],
            pipeline_jobs=[
                {
                    "job_id": "job-1",
                    "context_id": str(context_id),
                    "correlation_id": "corr-1",
                    "command": "generate_policy",
                    "status": "policy_generating",
                    "current_stage": "policy_generation",
                }
            ],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Policy pipeline" in response.data
    assert b"policy_generating" in response.data
    assert b"policy_generation" in response.data
    assert b"corr-1" in response.data
    assert b"disabled" in response.data


def test_context_detail_shows_failed_pipeline_job_diagnostics_in_development(client, monkeypatch):
    context_id = ObjectId()
    client.application.config["ENV"] = "development"
    monkeypatch.setattr(
        routes_module.mongo,
        "db",
        FakeDB(
            contexts=[{"_id": context_id, "status": "completed"}],
            interactions=[],
            pipeline_jobs=[
                {
                    "job_id": "job-failed",
                    "context_id": str(context_id),
                    "correlation_id": "corr-failed",
                    "command": "generate_policy",
                    "status": "failed",
                    "current_stage": "policy_generation",
                    "last_error": {
                        "error_code": "policy_agent_request_failed",
                        "failed_stage": "policy_generation",
                        "safe_message": "Policy generation failed.",
                    },
                }
            ],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get(f"/context/{context_id}")

    assert response.status_code == 200
    assert b"Status: <span id=\"pipeline-job-status\">failed</span>" in response.data
    assert b"Policy generation failed." in response.data
    assert b"policy_agent_request_failed" in response.data
    assert b"Failed stage:" in response.data
    assert b"Development diagnostics" in response.data
    assert b"/diagnostics/corr-failed" in response.data


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


def test_metrics_route_exposes_prometheus_payload(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    assert b"secpolicy_http_requests_total" in response.data


def test_ready_route_emits_structured_readiness_event(client, monkeypatch, caplog):
    monkeypatch.setattr(
        routes_module,
        "get_readiness_status",
        lambda: {
            "status": "not_ready",
            "service": "context-agent",
            "checks": {"mongo": {"status": "error", "reason": "ping_failed"}},
        },
    )
    caplog.set_level(logging.WARNING)

    response = client.get("/ready", headers={"X-Correlation-ID": "corr-ready"})

    assert response.status_code == 503
    event = json.loads(caplog.records[-1].message)
    assert event == {
        "correlation_id": "corr-ready",
        "error_code": "service_not_ready",
        "event": "readiness.route.completed",
        "method": "GET",
        "readiness_status": "not_ready",
        "result": "failure",
        "route": "/ready",
        "service": "context-agent",
        "stage": "readiness",
        "status_code": 503,
    }


def test_system_status_route_returns_aggregated_status(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {
            "status": "not_ready",
            "services": [{"service": "policy-agent", "status": "not_ready"}],
            "rag": {"status": "requires_refresh"},
        },
    )

    response = client.get("/system/status")

    assert response.status_code == 503
    assert response.get_json()["rag"]["status"] == "requires_refresh"


def test_system_status_route_returns_200_when_ready(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {
            "status": "ready",
            "services": [{"service": "policy-agent", "status": "ready"}],
            "rag": {"status": "ready"},
        },
    )

    response = client.get("/system/status")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"


def test_system_refresh_redirects_with_flash(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "refresh_system_state",
        lambda: {"success": True, "status": {"status": "ready"}},
    )

    response = client.post("/system/refresh", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("success", "System state refreshed successfully.") in flashes


def test_system_refresh_redirects_with_failure_flash(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "refresh_system_state",
        lambda: {
            "success": False,
            "response": {"message": "RAG refresh is disabled for this runtime."},
        },
    )

    response = client.post("/system/refresh", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("danger", "RAG refresh is disabled for this runtime.") in flashes


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


def _insert_policy_ready_context(context_id):
    security_context = routes_module.build_context_security_context({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
    })
    routes_module.mongo.db.contexts.insert_one({
        "_id": ObjectId(context_id),
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "status": "context_plan_approved",
        "security_context": security_context,
        "context_building": {
            "version": "1.0",
            "status": "sufficient",
            "questions": [],
            "missing_information": [],
        },
        "context_intelligence_plan": routes_module.approve_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })


def test_trigger_policy_generation_redirects_after_starting_job(client, monkeypatch):
    context_id = str(ObjectId())
    _insert_policy_ready_context(context_id)
    captured = {}
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )
    monkeypatch.setattr(
        routes_module,
        "find_active_pipeline_job",
        lambda current_context_id: None,
    )

    def fake_create_pipeline_job(**kwargs):
        captured.update(kwargs)
        return {
            "job_id": "job-1",
            "context_id": kwargs["context_id"],
            "correlation_id": "corr-1",
            "command": kwargs["command"],
            "status": "queued",
            "current_stage": "queued",
        }

    monkeypatch.setattr(routes_module, "create_pipeline_job", fake_create_pipeline_job)
    monkeypatch.setattr(
        routes_module,
        "start_pipeline_job_worker",
        lambda job: {"started": True, "job_id": job["job_id"]},
    )

    response = client.post(f"/context/{context_id}/generate_policy", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    assert captured["context_id"] == context_id
    assert captured["command"] == "generate_policy"
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("info", "Policy generation started. Current stage: queued.") in flashes


def test_trigger_policy_generation_reuses_active_job(client, monkeypatch):
    context_id = str(ObjectId())
    _insert_policy_ready_context(context_id)
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )
    monkeypatch.setattr(
        routes_module,
        "find_active_pipeline_job",
        lambda current_context_id: {
            "job_id": "job-active",
            "context_id": current_context_id,
            "correlation_id": "corr-active",
            "command": "generate_policy",
            "status": "policy_generating",
            "current_stage": "policy_generation",
        },
    )
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("must not create a second active job"),
    )

    response = client.post(f"/context/{context_id}/generate_policy", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert (
        "info",
        "Policy generation is already running. Current stage: policy_generation.",
    ) in flashes


def test_trigger_policy_generation_returns_json_accepted_job(client, monkeypatch):
    context_id = str(ObjectId())
    _insert_policy_ready_context(context_id)
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )
    monkeypatch.setattr(routes_module, "find_active_pipeline_job", lambda current_context_id: None)
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: {
            "job_id": "job-1",
            "context_id": kwargs["context_id"],
            "correlation_id": "corr-1",
            "command": kwargs["command"],
            "status": "queued",
            "current_stage": "queued",
            "last_error": {
                "error_code": "should_not_be_present",
                "raw_exception": "must not leak",
            },
        },
    )
    monkeypatch.setattr(
        routes_module,
        "start_pipeline_job_worker",
        lambda job: {"started": True, "job_id": job["job_id"]},
    )

    response = client.post(
        f"/context/{context_id}/generate_policy",
        headers={"Accept": "application/json", "X-Correlation-ID": "corr-1"},
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["status"] == "accepted"
    assert payload["job"]["job_id"] == "job-1"
    assert payload["job"]["current_stage"] == "queued"
    assert "raw_exception" not in payload["job"]["last_error"]


def test_trigger_policy_generation_blocks_when_runtime_is_not_ready(client, monkeypatch):
    context_id = str(ObjectId())
    _insert_policy_ready_context(context_id)
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "not_ready", "services": [], "rag": {"status": "requires_refresh"}},
    )
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("job must not be created when runtime is not ready"),
    )

    response = client.post(f"/context/{context_id}/generate_policy", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("danger", "Application runtime is not ready. Update state before generating a policy.") in flashes


def test_trigger_policy_generation_blocks_unapproved_context_plan_json(client, monkeypatch):
    context_id = str(ObjectId())
    security_context = routes_module.build_context_security_context({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
    })
    routes_module.mongo.db.contexts.insert_one({
        "_id": ObjectId(context_id),
        "security_context": security_context,
        "context_building": {"status": "sufficient"},
        "context_intelligence_plan": routes_module.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("job must not be created before plan approval"),
    )

    response = client.post(
        f"/context/{context_id}/generate_policy",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "context_plan_not_approved"


def test_trigger_policy_generation_blocks_context_building_questions_json(client, monkeypatch):
    context_id = str(ObjectId())
    routes_module.mongo.db.contexts.insert_one({
        "_id": ObjectId(context_id),
        "context_building": {"status": "needs_information"},
        "context_intelligence_plan": {"status": "approved"},
        "security_context": routes_module.build_context_security_context({
            "country": "Spain",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("job must not be created before context building completes"),
    )

    response = client.post(
        f"/context/{context_id}/generate_policy",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "context_building_needs_information"


def test_trigger_policy_generation_blocks_missing_plan_json(client, monkeypatch):
    context_id = str(ObjectId())
    routes_module.mongo.db.contexts.insert_one({
        "_id": ObjectId(context_id),
        "context_building": {"status": "sufficient"},
        "security_context": routes_module.build_context_security_context({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: pytest.fail("domain gating must run before runtime readiness"),
    )
    monkeypatch.setattr(
        routes_module,
        "create_pipeline_job",
        lambda **kwargs: pytest.fail("job must not be created without a plan"),
    )

    response = client.post(
        f"/context/{context_id}/generate_policy",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "context_plan_not_available"


def test_get_pipeline_job_status_returns_public_job(client, monkeypatch):
    client.application.config["ENV"] = "development"
    monkeypatch.setattr(
        routes_module,
        "get_pipeline_job",
        lambda job_id: {
            "job_id": job_id,
            "context_id": "ctx-1",
            "correlation_id": "corr-1",
            "command": "generate_policy",
            "status": "failed",
            "current_stage": "policy_generation",
            "last_error": {
                "error_code": "policy_agent_timeout",
                "safe_message": "Policy generation timed out.",
                "raw_exception": "must not leak",
            },
        },
    )

    response = client.get("/pipeline/jobs/job-1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["job"]["job_id"] == "job-1"
    assert payload["job"]["last_error"] == {
        "error_code": "policy_agent_timeout",
        "safe_message": "Policy generation timed out.",
    }
    assert payload["job"]["diagnostic_url"] == "/diagnostics/corr-1"


def test_get_active_pipeline_job_status_returns_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(routes_module, "find_active_pipeline_job", lambda context_id: None)

    response = client.get("/context/ctx-1/pipeline/jobs/active")

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "active_pipeline_job_not_found"


def test_context_system_refresh_redirects_back_to_context(client, monkeypatch):
    context_id = str(ObjectId())
    monkeypatch.setattr(
        routes_module,
        "refresh_system_state",
        lambda: {"success": True, "status": {"status": "ready"}},
    )

    response = client.post(f"/context/{context_id}/system/refresh", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/context/{context_id}")
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert ("success", "System state refreshed successfully.") in flashes


def test_get_diagnostics_route_returns_document(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "get_pipeline_diagnostic",
        lambda correlation_id: {
            "_id": "diag-1",
            "correlation_id": correlation_id,
            "context_id": "ctx-1",
            "status": "completed",
            "raw_response": "must-not-leak",
            "hops": [
                {
                    "service": "context-agent",
                    "stage": "validation",
                    "operation": "validate_policy",
                    "target_service": "validator-agent",
                    "outcome": "success",
                    "raw_response": "must-not-leak",
                }
            ],
        },
    )

    response = client.get("/diagnostics/corr-1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["correlation_id"] == "corr-1"
    assert payload["hops"] == [
        {
            "service": "context-agent",
            "stage": "validation",
            "operation": "validate_policy",
            "target_service": "validator-agent",
            "outcome": "success",
        }
    ]
    assert "_id" not in payload
    assert "raw_response" not in payload


def test_get_diagnostics_route_returns_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(routes_module, "get_pipeline_diagnostic", lambda correlation_id: None)

    response = client.get("/diagnostics/corr-missing")

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "diagnostic_not_found"


def test_dashboard_route_adds_security_headers(client, monkeypatch):
    monkeypatch.setattr(routes_module.mongo, "db", FakeDB(), raising=False)
    monkeypatch.setattr(
        routes_module,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Correlation-ID"]
