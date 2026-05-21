from types import SimpleNamespace

import pytest
import requests
from bson import ObjectId

from test_base import *
from app.services import logic


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def insert_one(self, document):
        self.docs.append(document)
        return SimpleNamespace(inserted_id=document.get("_id"))

    def update_one(self, query, update, upsert=False):
        target = self.find_one(query)
        if target is None:
            if not upsert:
                return SimpleNamespace(matched_count=0, modified_count=0)
            target = {}
            self.docs.append(target)

        conflicting_paths = set(update.get("$setOnInsert", {})).intersection(update.get("$set", {}))
        if conflicting_paths:
            raise ValueError(f"conflicting update paths: {sorted(conflicting_paths)}")

        for key, value in update.get("$setOnInsert", {}).items():
            target.setdefault(key, value)
        for key, value in update.get("$set", {}).items():
            target[key] = value
        for key, value in update.get("$push", {}).items():
            target.setdefault(key, [])
            if isinstance(value, dict) and "$each" in value:
                target[key].extend(value["$each"])
                if "$slice" in value:
                    target[key] = target[key][value["$slice"]:]
            else:
                target[key].append(value)
        return SimpleNamespace(matched_count=1, modified_count=1)


class FakeDB:
    def __init__(self, contexts=None, interactions=None, pipeline_diagnostics=None):
        self.contexts = FakeCollection(contexts)
        self.interactions = FakeCollection(interactions)
        self.pipeline_diagnostics = FakeCollection(pipeline_diagnostics)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._payload


def test_get_context_and_prompt_prefers_context_refined_prompt(monkeypatch):
    context_id = ObjectId()
    security_context = logic.build_context_security_context(
        {
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient data",
            "need": "Protect patient data",
        }
    )
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "status": "context_ready_for_policy",
                "refined_prompt": "canonical refined prompt",
                "language": "es",
                "version": "1.2.3",
                "security_context": security_context,
            }
        ],
        interactions=[
            {
                "context_id": context_id,
                "question_id": "refined_prompt",
                "answer": "legacy refined prompt",
            }
        ],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    assert payload["refined_prompt"] == "canonical refined prompt"
    assert payload["language"] == "es"
    assert payload["model_version"] == "1.2.3"
    assert payload["business_context"]["country"] == "Spain"
    assert payload["business_context"]["sector"] == "Healthcare"
    assert payload["business_context"]["critical_assets"] == ["Patient data"]


def test_get_context_and_prompt_falls_back_to_legacy_interaction(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[{"_id": context_id, "status": "context_ready_for_policy", "language": "en", "version": "0.2.0"}],
        interactions=[
            {
                "context_id": context_id,
                "question_id": "refined_prompt",
                "answer": "legacy refined prompt",
            }
        ],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    assert payload["refined_prompt"] == "legacy refined prompt"
    assert payload["language"] == "en"
    assert payload["model_version"] == "0.2.0"
    assert payload["business_context"]["country"] is None


def test_get_context_and_prompt_normalizes_numeric_model_version(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "status": "context_ready_for_policy",
                "refined_prompt": "prompt",
                "language": "en",
                "version": 1,
            }
        ],
        interactions=[],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    assert payload["model_version"] == "1"


def test_get_health_status_returns_static_liveness_payload():
    assert logic.get_health_status() == {
        "status": "ok",
        "service": "context-agent",
    }


def test_build_context_security_context_uses_context_fields_and_additional_need():
    security_context = logic.build_context_security_context(
        {
            "country": "Spain",
            "sector": "Professional services",
            "important_assets": "Client files",
            "critical_assets": "Contracts",
            "need": "Protect client confidentiality",
        },
        additional_need="Add incident response requirements.",
    )

    assert security_context["profile"]["operating_countries"] == ["Spain"]
    assert security_context["profile"]["sector"] == "Professional services"
    assert security_context["policy_intent"]["need"] == (
        "Protect client confidentiality\nAdd incident response requirements."
    )


def test_build_context_intelligence_plan_creates_reviewable_tasks():
    plan = logic.build_context_intelligence_plan({
        "country": "Spain",
        "sector": "Professional services",
        "company_activity": "IT consulting",
        "critical_assets": "Client contracts",
        "data_categories": "client_confidential_data",
        "need": "Build a security plan",
    })

    assert plan["version"] == logic.CONTEXT_INTELLIGENCE_PLAN_VERSION
    assert plan["status"] == "draft"
    assert plan["review"]["required"] is True
    assert [task["order"] for task in plan["tasks"]] == list(range(1, len(plan["tasks"]) + 1))
    assert plan["tasks"][0]["id"] == "company_profile"
    assert plan["tasks"][-1]["id"] == "final_synthesis"
    assert plan["context_snapshot"]["sector"] == "Professional services"
    assert "client_confidential_data" in plan["context_snapshot"]["data_categories"]
    assert plan["approved_revision_id"] is None
    assert plan["revisions"] == []


def test_build_context_intelligence_plan_preserves_existing_revisions():
    existing_plan = logic.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Professional services",
        "critical_assets": "Client contracts",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Professional services",
            "critical_assets": "Client contracts",
            "need": "Build a security plan",
        }),
    })

    rebuilt = logic.build_context_intelligence_plan(
        {
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        },
        existing_plan=existing_plan,
    )

    assert rebuilt["status"] == "draft"
    assert rebuilt["approved_revision_id"] is None
    assert rebuilt["revisions"] == existing_plan["revisions"]
    assert rebuilt["context_snapshot"]["sector"] == "Healthcare"


def test_build_context_building_state_creates_questions_for_missing_required_context():
    security_context = logic.build_context_security_context({
        "country": "Spain",
        "need": "Build a security plan",
    })

    context_building = logic.build_context_building_state(
        {"country": "Spain", "need": "Build a security plan"},
        security_context=security_context,
    )

    assert context_building["status"] == "needs_information"
    assert context_building["version"] == logic.CONTEXT_BUILDING_VERSION
    assert context_building["missing_information"] == [
        "profile.sector",
        "information_assets.critical_assets",
    ]
    assert [question["field_path"] for question in context_building["questions"]] == [
        "profile.sector",
        "information_assets.critical_assets",
    ]
    assert context_building["questions"][0]["answer_field"] == "sector"


def test_apply_context_building_answers_rebuilds_security_context_and_plan():
    context = {
        "country": "Spain",
        "need": "Build a security plan",
    }
    security_context = logic.build_context_security_context(context)
    context["security_context"] = security_context
    context["context_building"] = logic.build_context_building_state(
        context,
        security_context=security_context,
    )

    result = logic.apply_context_building_answers(
        context,
        {
            "context_building_profile_sector": "Healthcare",
            "context_building_information_assets_critical_assets": "Patient records",
        },
    )

    assert result["status"] == "awaiting_task_validation"
    assert result["answer_updates"] == {
        "sector": "Healthcare",
        "critical_assets": "Patient records",
    }
    assert result["context_building"]["status"] == "sufficient"
    assert {
        question["status"]
        for question in result["context_building"]["questions"]
    } == {"answered"}
    assert result["security_context"]["profile"]["sector"] == "Healthcare"
    assert result["context_intelligence_plan"]["context_snapshot"]["sector"] == "Healthcare"


def test_defer_context_building_question_keeps_context_building_blocked():
    context = {
        "country": "Spain",
        "need": "Build a security plan",
    }
    security_context = logic.build_context_security_context(context)
    context["context_building"] = logic.build_context_building_state(
        context,
        security_context=security_context,
    )

    result = logic.defer_context_building_question(
        context,
        "context_building_profile_sector",
        "Waiting for the CIO.",
    )

    assert result["success"] is True
    assert result["status"] == "context_building_needs_input"
    assert result["context_building"]["status"] == "needs_information"
    question = next(
        item
        for item in result["context_building"]["questions"]
        if item["id"] == "context_building_profile_sector"
    )
    assert question["status"] == "deferred"
    assert question["deferred_reason"] == "Waiting for the CIO."


def test_context_building_state_can_be_bypassed_for_fixture_imports():
    context_building = logic.build_context_building_state(
        {},
        bypassed=True,
    )

    assert context_building["status"] == "approved"
    assert context_building["bypassed"] is True


def test_approve_context_intelligence_plan_marks_tasks_and_feedback():
    context = {
        "country": "Spain",
        "sector": "Professional services",
        "critical_assets": "Client contracts",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Professional services",
            "critical_assets": "Client contracts",
            "need": "Build a security plan",
        }),
    }

    approved = logic.approve_context_intelligence_plan(
        context,
        "Add supplier review to the execution scope.",
    )

    assert approved["status"] == "approved"
    assert approved["review"]["required"] is False
    assert approved["review"]["user_feedback"] == "Add supplier review to the execution scope."
    assert approved["review"]["approval_notes"] == "Add supplier review to the execution scope."
    assert approved["review"]["approved_at"]
    assert approved["review"]["approved_by"] == "user"
    assert approved["review"]["approval_source"] == "ui"
    assert approved["review"]["context_snapshot_hash"]
    assert approved["approved_revision_id"] == "plan-rev-1"
    assert len(approved["revisions"]) == 1
    assert approved["revisions"][0]["revision_id"] == "plan-rev-1"
    assert approved["revisions"][0]["approval_notes"] == "Add supplier review to the execution scope."
    assert approved["revisions"][0]["context_snapshot_hash"] == approved["review"]["context_snapshot_hash"]
    assert {task["status"] for task in approved["tasks"]} == {"approved"}


def test_approve_context_intelligence_plan_preserves_previous_revision():
    context = {
        "country": "Spain",
        "sector": "Professional services",
        "critical_assets": "Client contracts",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.approve_context_intelligence_plan({
            "country": "Spain",
            "sector": "Professional services",
            "critical_assets": "Client contracts",
            "need": "Build a security plan",
            "context_intelligence_plan": logic.build_context_intelligence_plan({
                "country": "Spain",
                "sector": "Professional services",
                "critical_assets": "Client contracts",
                "need": "Build a security plan",
            }),
        }),
    }
    first_revision = dict(context["context_intelligence_plan"]["revisions"][0])

    approved = logic.approve_context_intelligence_plan(
        context,
        "Second approval after re-planning.",
        approved_by="fixture-import",
        approval_source="generate_from_yaml",
    )

    assert approved["approved_revision_id"] == "plan-rev-2"
    assert len(approved["revisions"]) == 2
    assert approved["revisions"][0] == first_revision
    assert approved["revisions"][1]["approval_source"] == "generate_from_yaml"


def test_context_plan_revision_returns_active_revision():
    plan = logic.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Professional services",
        "critical_assets": "Client contracts",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Professional services",
            "critical_assets": "Client contracts",
            "need": "Build a security plan",
        }),
    })

    revision = logic.context_plan_revision(plan)

    assert revision["revision_id"] == plan["approved_revision_id"]
    assert revision["context_snapshot_hash"] == plan["review"]["context_snapshot_hash"]


def test_run_structured_with_agent_falls_back_to_text_agent(monkeypatch):
    captured = {}

    class FakeAgent:
        def create(self, context_id=None):
            captured["created_context_id"] = context_id

        def run(self, prompt, context_id):
            captured["prompt"] = prompt
            captured["run_context_id"] = context_id
            return "plain task result"

    monkeypatch.setattr(logic, "create_agent_from_config", lambda config_path: FakeAgent())

    result = logic.run_structured_with_agent(
        "Task prompt",
        schema_name="context_agent_task_result",
        json_schema={"type": "object"},
        context_id="ctx-1",
    )

    assert captured == {
        "created_context_id": "ctx-1",
        "prompt": "Task prompt",
        "run_context_id": "ctx-1",
    }
    assert result["raw_text"] == "plain task result"
    assert result["findings"] == ["plain task result"]


def test_run_context_planning_review_uses_planning_schema(monkeypatch):
    captured = {}

    def fake_structured(
        prompt,
        *,
        schema_name,
        json_schema,
        context_id=None,
        model_version=None,
        fallback_phase=None,
    ):
        captured.update({
            "prompt": prompt,
            "schema_name": schema_name,
            "json_schema": json_schema,
            "context_id": context_id,
            "model_version": model_version,
            "fallback_phase": fallback_phase,
        })
        return {
            "plan_summary": "Review the analysis plan before execution.",
            "tasks": [
                {
                    "id": "company_profile",
                    "order": 1,
                    "title": "Company profile",
                    "objective": "Clarify the operating model.",
                    "dependencies": [],
                    "expected_output": "Confirmed operating model.",
                }
            ],
            "missing_context_questions": [
                {
                    "answer_field": "critical_assets",
                    "question": "Which assets are critical?",
                    "rationale": "Policy scope depends on critical assets.",
                }
            ],
            "approval_recommendation": "add_context",
        }

    monkeypatch.setattr(logic, "run_structured_with_agent", fake_structured)

    result = logic.run_context_planning_review(
        "Plan this context",
        context_id="ctx-1",
        model_version="0.1.0",
    )

    assert captured["schema_name"] == "context_agent_planning_review"
    assert captured["fallback_phase"] == "context_planning"
    assert captured["json_schema"]["required"] == [
        "plan_summary",
        "tasks",
        "missing_context_questions",
        "approval_recommendation",
    ]
    assert result["structured_review"]["approval_recommendation"] == "add_context"
    assert "Context planning review" in result["text"]
    assert "Which assets are critical?" in result["text"]


def test_run_structured_with_agent_planning_fallback(monkeypatch):
    class FakeAgent:
        def create(self, context_id=None):
            pass

        def run(self, prompt, context_id):
            return "Plain planning review"

    monkeypatch.setattr(logic, "create_agent_from_config", lambda config_path: FakeAgent())

    result = logic.run_structured_with_agent(
        "Planning prompt",
        schema_name="context_agent_planning_review",
        json_schema={"type": "object"},
        context_id="ctx-1",
        fallback_phase="context_planning",
    )

    assert result["plan_summary"] == "Plain planning review"
    assert result["tasks"] == []
    assert result["missing_context_questions"] == []
    assert result["approval_recommendation"] == "review_required"


def test_run_context_building_review_uses_context_building_schema(monkeypatch):
    captured = {}

    def fake_structured(
        prompt,
        *,
        schema_name,
        json_schema,
        context_id=None,
        model_version=None,
        fallback_phase=None,
    ):
        captured.update({
            "prompt": prompt,
            "schema_name": schema_name,
            "json_schema": json_schema,
            "context_id": context_id,
            "model_version": model_version,
            "fallback_phase": fallback_phase,
        })
        return {
            "summary": "Context update reviewed.",
            "explicit_facts": [
                {
                    "field_path": "critical_assets",
                    "value": "Patient data",
                    "source": "user_input",
                }
            ],
            "assumptions": ["Access reviews are monthly."],
            "missing_information": [],
            "follow_up_questions": [
                {
                    "id": "q_retention",
                    "answer_field": "data_retention",
                    "question": "How long is patient data retained?",
                    "rationale": "Retention affects policy obligations.",
                }
            ],
            "security_domains": ["data_protection"],
            "rag_retrieval_hints": {
                "collection_families": [],
                "jurisdictions": [],
                "sectors": [],
                "methodologies": [],
                "query_terms": ["patient data retention"],
            },
            "next_action": "ask_follow_up",
        }

    monkeypatch.setattr(logic, "run_structured_with_agent", fake_structured)

    result = logic.run_context_building_review(
        "Update this context",
        context_id="ctx-1",
        model_version="0.1.0",
    )

    assert captured["schema_name"] == "context_agent_context_building_review"
    assert captured["fallback_phase"] == "context_building"
    assert "follow_up_questions" in captured["json_schema"]["properties"]
    assert result["structured_review"]["next_action"] == "ask_follow_up"
    assert "Context building review" in result["text"]
    assert "How long is patient data retained?" in result["text"]


def test_run_structured_with_agent_context_building_fallback(monkeypatch):
    class FakeAgent:
        def create(self, context_id=None):
            pass

        def run(self, prompt, context_id):
            return "Plain context-building review"

    monkeypatch.setattr(logic, "create_agent_from_config", lambda config_path: FakeAgent())

    result = logic.run_structured_with_agent(
        "Context-building prompt",
        schema_name="context_agent_context_building_review",
        json_schema={"type": "object"},
        context_id="ctx-1",
        fallback_phase="context_building",
    )

    assert result["summary"] == "Plain context-building review"
    assert result["explicit_facts"] == []
    assert result["follow_up_questions"] == []
    assert result["next_action"] == "review_required"


def test_execute_context_plan_requires_approved_revision(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "context_intelligence_plan": logic.build_context_intelligence_plan({
                    "country": "Spain",
                    "sector": "Healthcare",
                    "critical_assets": "Patient records",
                    "need": "Build a security plan",
                }),
            }
        ]
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        logic,
        "run_structured_with_agent",
        lambda *args, **kwargs: pytest.fail("draft plans must not execute"),
    )

    result = logic.execute_context_plan(str(context_id))

    assert result["success"] is False
    assert result["error_code"] == "context_plan_not_approved"
    assert "context_task_results" not in fake_db.contexts.docs[0]


def test_execute_context_plan_embeds_task_results_without_refined_prompt(monkeypatch):
    context_id = ObjectId()
    plan = logic.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    plan["tasks"] = plan["tasks"][:2]
    plan["revisions"][0]["tasks"] = plan["revisions"][0]["tasks"][:2]
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "country": "Spain",
                "sector": "Healthcare",
                "critical_assets": "Patient records",
                "need": "Build a security plan",
                "security_context": logic.build_context_security_context({
                    "country": "Spain",
                    "sector": "Healthcare",
                    "critical_assets": "Patient records",
                    "need": "Build a security plan",
                }),
                "context_intelligence_plan": plan,
                "refined_prompt": "must not be used",
            }
        ]
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)
    captured_prompts = []
    structured_response = {
        "task_id": "company_profile",
        "status": "completed",
        "findings": ["task result"],
        "assumptions": [],
        "missing_details": [],
        "risks": [],
        "policy_implications": ["Use this finding in the policy scope."],
        "rag_retrieval_hints": {
            "collection_families": ["controls"],
            "jurisdictions": ["Spain"],
            "sectors": ["Healthcare"],
            "methodologies": ["ISO 27001"],
            "query_terms": ["patient records access control"],
        },
    }

    monkeypatch.setattr(
        logic,
        "run_structured_with_agent",
        lambda prompt, **kwargs: captured_prompts.append((prompt, kwargs)) or structured_response,
    )

    result = logic.execute_context_plan(str(context_id))

    context = fake_db.contexts.docs[0]
    assert result["success"] is True
    assert result["plan_revision_id"] == "plan-rev-1"
    assert result["task_count"] == 2
    assert context["status"] == "context_plan_executed"
    assert context["context_task_results"]["status"] == "completed"
    assert context["context_task_results"]["plan_revision_id"] == "plan-rev-1"
    assert len(context["context_task_results"]["tasks"]) == 2
    assert context["context_task_results"]["tasks"][0]["structured_result"] == structured_response
    assert "Findings:" in context["context_task_results"]["tasks"][0]["result"]
    assert "RAG retrieval hints:" in context["context_task_results"]["tasks"][0]["result"]
    assert "refined_prompt" not in result
    assert all("must not be used" not in prompt for prompt, _kwargs in captured_prompts)
    assert {kwargs["schema_name"] for _prompt, kwargs in captured_prompts} == {
        "context_agent_task_result"
    }


def test_execute_context_plan_persists_safe_task_failure(monkeypatch):
    context_id = ObjectId()
    plan = logic.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "need": "Build a security plan",
        }),
    })
    plan["tasks"] = plan["tasks"][:1]
    plan["revisions"][0]["tasks"] = plan["revisions"][0]["tasks"][:1]
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "country": "Spain",
                "sector": "Healthcare",
                "critical_assets": "Patient records",
                "need": "Build a security plan",
                "security_context": logic.build_context_security_context({
                    "country": "Spain",
                    "sector": "Healthcare",
                    "critical_assets": "Patient records",
                    "need": "Build a security plan",
                }),
                "context_intelligence_plan": plan,
            }
        ]
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    def failing_agent(*args, **kwargs):
        raise RuntimeError("secret raw provider failure")

    monkeypatch.setattr(logic, "run_structured_with_agent", failing_agent)

    result = logic.execute_context_plan(str(context_id))

    context = fake_db.contexts.docs[0]
    assert result["success"] is False
    assert result["error_code"] == "context_task_execution_failed"
    assert "secret raw provider failure" not in result["message"]
    assert context["status"] == "context_plan_failed"
    assert context["context_task_results"]["status"] == "failed"
    assert context["context_task_results"]["tasks"][0]["error"]["error_code"] == (
        "context_task_execution_failed"
    )


def _completed_context_task_results():
    return {
        "version": "1.0",
        "status": "completed",
        "plan_revision_id": "plan-rev-1",
        "context_snapshot_hash": "hash-1",
        "tasks": [
            {
                "task_id": "company_profile",
                "title": "Company profile",
                "status": "completed",
                "result": "The company operates a healthcare clinic in Spain.",
            },
            {
                "task_id": "information_assets",
                "title": "Information assets",
                "status": "completed",
                "result": "Patient records are the primary critical asset.",
            },
        ],
    }


def _completed_structured_context_task_results():
    task_results = _completed_context_task_results()
    task_results["tasks"][0]["structured_result"] = {
        "task_id": "company_profile",
        "status": "completed",
        "findings": ["The company operates a healthcare clinic in Spain."],
        "assumptions": ["The clinic handles outpatient care."],
        "missing_details": ["No named security owner was provided."],
        "risks": ["Patient data access could be over-permissive."],
        "policy_implications": ["Access review responsibilities must be explicit."],
        "rag_retrieval_hints": {
            "collection_families": ["controls"],
            "jurisdictions": ["Spain"],
            "sectors": ["Healthcare"],
            "methodologies": ["ISO 27001"],
            "query_terms": ["healthcare access review"],
        },
    }
    return task_results


def _approved_context_plan():
    return logic.approve_context_intelligence_plan({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
        "context_intelligence_plan": logic.build_context_intelligence_plan({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "data_categories": "health_data",
            "need": "Build a security plan",
        }),
    })


def test_synthesize_final_context_requires_completed_task_results(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "country": "Spain",
                "sector": "Healthcare",
                "critical_assets": "Patient records",
                "need": "Build a security plan",
                "context_intelligence_plan": _approved_context_plan(),
            }
        ]
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.synthesize_final_context(str(context_id))

    assert result["success"] is False
    assert result["error_code"] == "context_task_results_not_completed"
    assert "final_context" not in fake_db.contexts.docs[0]
    assert "refined_prompt" not in fake_db.contexts.docs[0]


def test_synthesize_final_context_persists_final_context_and_refined_prompt(monkeypatch):
    context_id = ObjectId()
    security_context = logic.build_context_security_context({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
    })
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "country": "Spain",
                "sector": "Healthcare",
                "critical_assets": "Patient records",
                "data_categories": "health_data",
                "need": "Build a security plan",
                "security_context": security_context,
                "context_intelligence_plan": _approved_context_plan(),
                "context_task_results": _completed_context_task_results(),
            }
        ],
        interactions=[],
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.synthesize_final_context(str(context_id))

    context = fake_db.contexts.docs[0]
    assert result["success"] is True
    assert context["status"] == "context_ready_for_policy"
    assert context["final_context"]["status"] == "ready"
    assert context["final_context"]["context_ready_for_policy"] is True
    assert context["final_context"]["plan_revision_id"] == "plan-rev-1"
    assert "Patient records" in context["refined_prompt"]
    payload = logic.get_context_and_prompt(str(context_id))
    assert payload["refined_prompt"] == context["refined_prompt"]


def test_build_final_context_expands_structured_task_result_fields():
    security_context = logic.build_context_security_context({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
    })
    context = {
        "security_context": security_context,
        "context_task_results": _completed_structured_context_task_results(),
    }
    plan_revision = logic.context_plan_revision(_approved_context_plan())

    final_context = logic.build_final_context(
        context,
        security_context=security_context,
        plan_revision=plan_revision,
    )

    item = final_context["sections"]["task_findings"]["items"][0]
    assert item["findings"] == ["The company operates a healthcare clinic in Spain."]
    assert item["risks"] == ["Patient data access could be over-permissive."]
    assert item["policy_implications"] == [
        "Access review responsibilities must be explicit."
    ]
    assert item["rag_retrieval_hints"]["query_terms"] == ["healthcare access review"]
    assert "Findings:" in item["content"]
    assert "RAG retrieval hints:" in final_context["sections"]["task_findings"]["content"]


def test_get_context_and_prompt_includes_structured_policy_handoff(monkeypatch):
    context_id = ObjectId()
    security_context = logic.build_context_security_context({
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "methodology": "ISO 27001",
        "need": "Build a security plan",
    })
    context = {
        "_id": context_id,
        "status": "context_ready_for_policy",
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "methodology": "ISO 27001",
        "need": "Build a security plan",
        "language": "en",
        "version": "1.0",
        "security_context": security_context,
        "context_intelligence_plan": _approved_context_plan(),
        "context_task_results": _completed_structured_context_task_results(),
    }
    context["final_context"] = logic.build_final_context(
        context,
        security_context=security_context,
        plan_revision=logic.context_plan_revision(context["context_intelligence_plan"]),
    )
    context["refined_prompt"] = logic.render_final_context_prompt(context["final_context"])
    fake_db = FakeDB(contexts=[context], interactions=[])
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    payload = logic.get_context_and_prompt(str(context_id))

    handoff = payload["policy_handoff_context"]
    assert payload["business_context"]["sector"] == "Healthcare"
    assert handoff["business_context"]["sector"] == "Healthcare"
    assert handoff["plan_revision_id"] == "plan-rev-1"
    assert handoff["structured_findings"][0]["findings"] == [
        "The company operates a healthcare clinic in Spain."
    ]
    assert handoff["structured_findings"][0]["policy_implications"] == [
        "Access review responsibilities must be explicit."
    ]
    assert handoff["retrieval_hints"]["collection_families"][:1] == ["legal_norms"]
    assert "risk_methodologies" in handoff["retrieval_hints"]["collection_families"]
    assert "controls" in handoff["retrieval_hints"]["collection_families"]
    assert "health_data" in handoff["retrieval_hints"]["data_types"]
    assert "healthcare access review" in handoff["retrieval_hints"]["query_terms"]


def test_synthesize_final_context_rejects_missing_security_context_information(monkeypatch):
    context_id = ObjectId()
    security_context = logic.build_context_security_context({
        "country": "Spain",
        "need": "Build a security plan",
    })
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "country": "Spain",
                "need": "Build a security plan",
                "security_context": security_context,
                "context_intelligence_plan": _approved_context_plan(),
                "context_task_results": _completed_context_task_results(),
            }
        ],
        interactions=[],
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.synthesize_final_context(str(context_id))

    assert result["success"] is False
    assert result["error_code"] == "security_context_not_sufficient"
    assert "final_context" not in fake_db.contexts.docs[0]
    assert "refined_prompt" not in fake_db.contexts.docs[0]


def test_synthesize_final_context_rejects_plan_revision_mismatch(monkeypatch):
    context_id = ObjectId()
    task_results = _completed_context_task_results()
    task_results["plan_revision_id"] = "plan-rev-outdated"
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "country": "Spain",
                "sector": "Healthcare",
                "critical_assets": "Patient records",
                "data_categories": "health_data",
                "need": "Build a security plan",
                "security_context": logic.build_context_security_context({
                    "country": "Spain",
                    "sector": "Healthcare",
                    "critical_assets": "Patient records",
                    "data_categories": "health_data",
                    "need": "Build a security plan",
                }),
                "context_intelligence_plan": _approved_context_plan(),
                "context_task_results": task_results,
            }
        ],
        interactions=[],
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.synthesize_final_context(str(context_id))

    assert result["success"] is False
    assert result["error_code"] == "context_task_results_revision_mismatch"
    assert "final_context" not in fake_db.contexts.docs[0]


def test_mark_final_context_section_for_improvement_blocks_policy_handoff(monkeypatch):
    context_id = ObjectId()
    context = {
        "_id": context_id,
        "status": "context_ready_for_policy",
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
        "security_context": logic.build_context_security_context({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "data_categories": "health_data",
            "need": "Build a security plan",
        }),
        "context_intelligence_plan": _approved_context_plan(),
        "context_task_results": _completed_context_task_results(),
    }
    context["final_context"] = logic.build_final_context(
        context,
        security_context=context["security_context"],
        plan_revision=logic.context_plan_revision(context["context_intelligence_plan"]),
    )
    context["refined_prompt"] = logic.render_final_context_prompt(context["final_context"])
    fake_db = FakeDB(contexts=[context], interactions=[])
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.mark_final_context_sections_for_improvement(
        str(context_id),
        {"security_scope": "Clarify third-party laboratory dependencies."},
    )

    updated_context = fake_db.contexts.docs[0]
    assert result["success"] is True
    assert updated_context["status"] == "final_context_needs_improvement"
    assert updated_context["final_context"]["context_ready_for_policy"] is False
    assert updated_context["final_context"]["sections"]["security_scope"]["status"] == "needs_improvement"
    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.get_context_and_prompt(str(context_id))
    assert exc_info.value.error_code == "context_not_ready_for_policy"


def test_regenerate_final_context_sections_restores_policy_handoff_and_records_lesson(monkeypatch):
    context_id = ObjectId()
    context = {
        "_id": context_id,
        "status": "context_ready_for_policy",
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
        "security_context": logic.build_context_security_context({
            "country": "Spain",
            "sector": "Healthcare",
            "critical_assets": "Patient records",
            "data_categories": "health_data",
            "need": "Build a security plan",
        }),
        "context_intelligence_plan": _approved_context_plan(),
        "context_task_results": _completed_context_task_results(),
    }
    context["final_context"] = logic.build_final_context(
        context,
        security_context=context["security_context"],
        plan_revision=logic.context_plan_revision(context["context_intelligence_plan"]),
    )
    context["refined_prompt"] = logic.render_final_context_prompt(context["final_context"])
    fake_db = FakeDB(contexts=[context], interactions=[])
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)
    logic.mark_final_context_sections_for_improvement(
        str(context_id),
        {"security_scope": "Clarify third-party laboratory dependencies."},
    )

    result = logic.regenerate_final_context_sections(str(context_id))

    updated_context = fake_db.contexts.docs[0]
    assert result["success"] is True
    assert result["regenerated_sections"] == ["security_scope"]
    assert updated_context["status"] == "context_ready_for_policy"
    assert updated_context["final_context"]["context_ready_for_policy"] is True
    assert "third-party laboratory" in updated_context["refined_prompt"]
    assert updated_context["context_lessons"][0]["status"] == "pending_review"
    assert updated_context["context_lessons"][0]["section_id"] == "security_scope"

    updated_context["context_lessons"][0]["status"] = "approved_for_export"
    export = logic.export_context_lessons(str(context_id))
    assert export["success"] is True
    assert export["count"] == 1
    assert export["lessons"][0]["lesson_id"] == "lesson-1"


def test_update_context_lesson_status_controls_export_eligibility(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "context_lessons": [
                    {
                        "lesson_id": "lesson-1",
                        "status": "pending_review",
                        "statement": "Review feedback should improve future contexts.",
                    }
                ],
            }
        ],
        interactions=[],
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.update_context_lesson_status(
        str(context_id),
        "lesson-1",
        "approved_for_export",
    )

    assert result["success"] is True
    assert result["lesson"]["status"] == "approved_for_export"
    export = logic.export_context_lessons(str(context_id))
    assert export["count"] == 1
    assert export["lessons"][0]["lesson_id"] == "lesson-1"


def test_public_security_context_payload_builds_context_for_legacy_records():
    payload = logic.public_security_context_payload(
        "context-1",
        {
            "country": "France",
            "sector": "E-commerce",
            "critical_assets": "Payment system",
            "need": "Protect online sales",
        },
    )

    assert payload["success"] is True
    assert payload["context_id"] == "context-1"
    assert payload["security_context_version"] == logic.SECURITY_CONTEXT_VERSION
    assert payload["security_context"]["profile"]["sector"] == "E-commerce"
    assert payload["security_context"]["retrieval_hints"]["sectors"] == ["E-commerce"]


def test_get_readiness_status_returns_ready_when_config_and_mongo_are_ok(app_context, monkeypatch):
    ping_calls = []

    def fake_ping(command_name):
        ping_calls.append(command_name)
        return {"ok": 1}

    monkeypatch.setattr(
        logic.mongo,
        "cx",
        SimpleNamespace(admin=SimpleNamespace(command=fake_ping)),
        raising=False,
    )
    logic.current_app.config["SECRET_KEY"] = "configured-test-secret"
    logic.current_app.config["MONGO_URI"] = "mongodb://mongo:27017/context-testdb"

    result = logic.get_readiness_status()

    assert result == {
        "status": "ready",
        "service": "context-agent",
        "checks": {
            "config": {"status": "ok", "missing": []},
            "mongo": {"status": "ok"},
        },
    }
    assert ping_calls == ["ping"]


def test_get_readiness_status_reports_missing_config_without_hiding_mongo_state(app_context, monkeypatch):
    monkeypatch.setattr(
        logic.mongo,
        "cx",
        SimpleNamespace(admin=SimpleNamespace(command=lambda command_name: {"ok": 1})),
        raising=False,
    )
    logic.current_app.config["SECRET_KEY"] = ""
    logic.current_app.config["MONGO_URI"] = ""

    result = logic.get_readiness_status()

    assert result == {
        "status": "not_ready",
        "service": "context-agent",
        "checks": {
            "config": {"status": "error", "missing": ["MONGO_URI", "SECRET_KEY"]},
            "mongo": {"status": "ok"},
        },
    }


def test_get_readiness_status_reports_mongo_failure(app_context, monkeypatch):
    def failing_ping(command_name):
        raise RuntimeError(f"{command_name} failed")

    monkeypatch.setattr(
        logic.mongo,
        "cx",
        SimpleNamespace(admin=SimpleNamespace(command=failing_ping)),
        raising=False,
    )
    logic.current_app.config["SECRET_KEY"] = "configured-test-secret"
    logic.current_app.config["MONGO_URI"] = "mongodb://mongo:27017/context-testdb"

    result = logic.get_readiness_status()

    assert result == {
        "status": "not_ready",
        "service": "context-agent",
        "checks": {
            "config": {"status": "ok", "missing": []},
            "mongo": {"status": "error", "reason": "ping_failed"},
        },
    }


def test_get_system_status_aggregates_services_and_rag(app_context, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        if url.endswith("/rag/status"):
            return FakeResponse(
                {
                    "status": "not_ready",
                    "rag": {
                        "status": "requires_refresh",
                        "missing_collections": ["normativa"],
                    },
                },
                503,
            )
        return FakeResponse({"status": "ready", "checks": {"config": {"status": "ok"}}}, 200)

    monkeypatch.setattr(logic.requests, "get", fake_get)
    monkeypatch.setattr(
        logic,
        "get_readiness_status",
        lambda: {"status": "ready", "checks": {"mongo": {"status": "ok"}}},
    )

    result = logic.get_system_status()

    assert result["status"] == "not_ready"
    assert [service["service"] for service in result["services"]] == [
        "context-agent",
        "policy-agent",
        "validator-agent",
    ]
    assert result["rag"]["status"] == "requires_refresh"
    assert calls[-1][0].endswith("/rag/status")
    assert calls[-1][1] == logic.SYSTEM_RAG_STATUS_TIMEOUT_SECONDS


def test_service_endpoint_status_reports_unreachable(monkeypatch):
    def fake_get(url, timeout):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(logic.requests, "get", fake_get)

    result = logic._service_endpoint_status("policy-agent", "http://policy-agent:5000")

    assert result == {
        "service": "policy-agent",
        "status": "unreachable",
        "status_code": None,
        "checks": {},
    }


def test_get_system_status_returns_ready_when_services_and_rag_are_ready(app_context, monkeypatch):
    def fake_get(url, timeout):
        if url.endswith("/rag/status"):
            return FakeResponse(
                {
                    "status": "ready",
                    "rag": {
                        "status": "ready",
                        "missing_collections": [],
                    },
                },
                200,
            )
        return FakeResponse({"status": "ready", "checks": {"config": {"status": "ok"}}}, 200)

    monkeypatch.setattr(logic.requests, "get", fake_get)
    monkeypatch.setattr(
        logic,
        "get_readiness_status",
        lambda: {"status": "ready", "checks": {"mongo": {"status": "ok"}}},
    )

    result = logic.get_system_status()

    assert result["status"] == "ready"
    assert all(service["status"] == "ready" for service in result["services"])
    assert result["rag"]["status"] == "ready"


def test_refresh_system_state_calls_policy_rag_refresh(app_context, monkeypatch):
    calls = []

    def fake_post(url, timeout, headers):
        calls.append((url, timeout, headers))
        return FakeResponse({"success": True, "stage": "rag_refresh"}, 200)

    monkeypatch.setattr(logic.requests, "post", fake_post)
    monkeypatch.setattr(
        logic,
        "get_system_status",
        lambda: {"status": "ready", "services": [], "rag": {"status": "ready"}},
    )

    result = logic.refresh_system_state()

    assert result["success"] is True
    assert calls[0][0].endswith("/rag/refresh")
    assert "X-Correlation-ID" in calls[0][2]
    assert result["status"]["status"] == "ready"


def test_refresh_system_state_reports_policy_refresh_failure(app_context, monkeypatch):
    def fake_post(url, timeout, headers):
        assert "X-Correlation-ID" in headers
        return FakeResponse(
            {
                "success": False,
                "error_code": "rag_refresh_disabled",
                "message": "RAG refresh is disabled for this runtime.",
            },
            403,
        )

    monkeypatch.setattr(logic.requests, "post", fake_post)
    monkeypatch.setattr(
        logic,
        "get_system_status",
        lambda: {"status": "not_ready", "services": [], "rag": {"status": "requires_refresh"}},
    )

    result = logic.refresh_system_state()

    assert result["success"] is False
    assert result["status_code"] == 403
    assert result["response"]["error_code"] == "rag_refresh_disabled"
    assert result["status"]["status"] == "not_ready"


def test_refresh_system_state_handles_unreachable_policy_agent(app_context, monkeypatch):
    def fake_post(url, timeout, headers):
        assert "X-Correlation-ID" in headers
        raise requests.exceptions.ConnectionError("policy-agent unavailable")

    monkeypatch.setattr(logic.requests, "post", fake_post)
    monkeypatch.setattr(
        logic,
        "get_system_status",
        lambda: {"status": "not_ready", "services": [], "rag": {"status": "unknown"}},
    )

    result = logic.refresh_system_state()

    assert result == {
        "success": False,
        "error_code": "policy_agent_unreachable",
        "message": "Policy agent is unreachable.",
        "status": {"status": "not_ready", "services": [], "rag": {"status": "unknown"}},
    }


def test_store_validated_policy_inserts_agent_interaction(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB()
    payload = {
        "policy_text": "Validated policy text",
        "generated_at": "2026-04-10T10:00:00+00:00",
        "policy_agent_version": "0.1.0",
        "language": "en",
        "status": "accepted",
        "recommendations": ["Keep evidence"],
    }

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.store_validated_policy(str(context_id), payload)

    assert result["success"] is True
    assert result["stage"] == "persistence"
    assert result["context_id"] == str(context_id)
    assert len(fake_db.interactions.docs) == 1
    stored = fake_db.interactions.docs[0]
    assert stored["context_id"] == context_id
    assert stored["question_id"] == "validated_policy"
    assert stored["answer"] == "Validated policy text"
    assert stored["policy_agent_version"] == "0.1.0"
    assert stored["language"] == "en"
    assert stored["status"] == "accepted"
    assert stored["recommendations"] == ["Keep evidence"]
    assert stored["ownership"] == {
        "owner_service": "context-agent",
        "source_of_truth": False,
        "view_type": "derived_policy_snapshot",
    }
    assert stored["policy_ref"] == {
        "owner_service": "policy-agent",
        "source_collection": "policies",
        "context_id": str(context_id),
    }
    assert stored["validation_ref"] == {
        "owner_service": "validator-agent",
        "source_collection": "validations",
        "context_id": str(context_id),
    }


def test_store_validated_policy_requires_full_payload(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB()

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.store_validated_policy(
            str(context_id),
            {
                "policy_text": "Validated policy text",
                "policy_agent_version": "0.1.0",
                "language": "en",
            },
        )

    assert exc_info.value.stage == "persistence"
    assert exc_info.value.error_code == "validated_policy_missing_fields"


def test_generate_full_policy_pipeline_stores_validated_policy_without_internal_http(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB()
    validated_payload = {
        "policy_text": "Validated policy text",
        "generated_at": "2026-04-10T10:00:00+00:00",
        "policy_agent_version": "0.1.0",
        "language": "en",
        "status": "review",
        "recommendations": ["Clarify retention period"],
    }

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        logic,
        "trigger_policy_generation",
        lambda current_context_id: {
            "success": True,
            "policy_data": {
                "context_id": current_context_id,
                "policy_text": "Draft policy text",
            },
        },
    )
    monkeypatch.setattr(logic, "call_validator_agent", lambda policy_data: validated_payload)

    def unexpected_http_call(*args, **kwargs):
        raise AssertionError("generate_full_policy_pipeline should not make internal HTTP callbacks")

    monkeypatch.setattr(logic.requests, "post", unexpected_http_call)

    result = logic.generate_full_policy_pipeline(str(context_id))

    assert result["success"] is True
    assert result["stage"] == "completed"
    assert result["validated_data"] == validated_payload
    assert result["persistence"]["stage"] == "persistence"
    assert len(fake_db.interactions.docs) == 1
    assert fake_db.interactions.docs[0]["answer"] == "Validated policy text"
    assert len(fake_db.pipeline_diagnostics.docs) == 1
    assert fake_db.pipeline_diagnostics.docs[0]["context_id"] == str(context_id)
    assert fake_db.pipeline_diagnostics.docs[0]["status"] == "completed"
    assert fake_db.pipeline_diagnostics.docs[0]["hops"][-1]["outcome"] == "success"


def test_generate_full_policy_pipeline_returns_structured_stage_error(monkeypatch):
    monkeypatch.setattr(
        logic,
        "trigger_policy_generation",
        lambda context_id: {
            "success": False,
            "stage": "policy_generation",
            "error_type": "dependency_error",
            "error_code": "policy_agent_request_failed",
            "message": "Policy generation failed.",
            "details": {"target_service": "policy-agent"},
            "status_code": 502,
        },
    )

    result = logic.generate_full_policy_pipeline("ctx-1")

    assert result == {
        "success": False,
        "stage": "policy_generation",
        "error_type": "dependency_error",
        "error_code": "policy_agent_request_failed",
        "message": "Policy generation failed.",
        "details": {"target_service": "policy-agent"},
        "status_code": 502,
    }


def test_call_policy_agent_propagates_timeout_and_correlation_headers(app_context, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse({"success": True, "policy_text": "generated"})

    monkeypatch.setattr(logic.requests, "post", fake_post)
    logic.current_app.config["POLICY_AGENT_TIMEOUT_SECONDS"] = 12.5

    result = logic.call_policy_agent(
        {
            "context_id": "ctx-1",
            "correlation_id": "corr-1",
            "refined_prompt": "prompt",
            "language": "en",
            "model_version": "0.1.0",
        }
    )

    assert result == {"success": True, "policy_text": "generated"}
    assert captured["url"].endswith("/generate_policy")
    assert captured["headers"] == {"X-Correlation-ID": "corr-1"}
    assert captured["timeout"] == 12.5


def test_call_policy_agent_surfaces_dependency_error_metadata(app_context, monkeypatch):
    def fake_post(url, json, headers, timeout):
        return FakeResponse(
            {
                "success": False,
                "error_type": "contract_error",
                "error_code": "invalid_field_type",
                "correlation_id": "policy-corr",
            },
            status_code=400,
        )

    monkeypatch.setattr(logic.requests, "post", fake_post)

    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.call_policy_agent(
            {
                "context_id": "ctx-2",
                "refined_prompt": "prompt",
                "language": "en",
                "model_version": "0.1.0",
            }
        )

    assert exc_info.value.error_code == "policy_agent_request_failed"
    assert exc_info.value.correlation_id == "ctx-2"
    assert exc_info.value.details == {
        "target_service": "policy-agent",
        "operation": "generate_policy",
        "dependency_status_code": 400,
        "dependency_error_type": "contract_error",
        "dependency_error_code": "invalid_field_type",
        "dependency_correlation_id": "policy-corr",
    }


def test_call_validator_agent_propagates_timeout_and_correlation_headers(app_context, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse({"status": "accepted"})

    monkeypatch.setattr(logic.requests, "post", fake_post)
    logic.current_app.config["VALIDATOR_AGENT_TIMEOUT_SECONDS"] = 18.0

    result = logic.call_validator_agent(
        {
            "context_id": "ctx-3",
            "correlation_id": "corr-3",
            "policy_text": "policy",
            "structured_plan": [],
            "generated_at": "2026-04-22T00:00:00+00:00",
        }
    )

    assert result == {"status": "accepted"}
    assert captured["url"].endswith("/validate-policy")
    assert captured["headers"] == {"X-Correlation-ID": "corr-3"}
    assert captured["timeout"] == 18.0


def test_call_validator_agent_surfaces_dependency_error_metadata(app_context, monkeypatch):
    def fake_post(url, json, headers, timeout):
        return FakeResponse(
            {
                "success": False,
                "error_type": "dependency_error",
                "error_code": "policy_update_request_failed",
                "correlation_id": "validator-corr",
            },
            status_code=502,
        )

    monkeypatch.setattr(logic.requests, "post", fake_post)

    with pytest.raises(logic.PipelineStepError) as exc_info:
        logic.call_validator_agent(
            {
                "context_id": "ctx-4",
                "policy_text": "policy",
                "structured_plan": [],
                "generated_at": "2026-04-22T00:00:00+00:00",
            }
        )

    assert exc_info.value.error_code == "validator_agent_request_failed"
    assert exc_info.value.correlation_id == "ctx-4"
    assert exc_info.value.details == {
        "target_service": "validator-agent",
        "operation": "validate_policy",
        "dependency_status_code": 502,
        "dependency_error_type": "dependency_error",
        "dependency_error_code": "policy_update_request_failed",
        "dependency_correlation_id": "validator-corr",
    }


def test_get_context_and_prompt_uses_request_correlation_id(monkeypatch, app):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "status": "context_ready_for_policy",
                "refined_prompt": "prompt",
                "language": "en",
                "version": "0.2.0",
            }
        ],
        interactions=[],
    )

    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    with app.test_request_context("/", headers={"X-Correlation-ID": "corr-request"}):
        app.preprocess_request()
        payload = logic.get_context_and_prompt(str(context_id))

    assert payload["correlation_id"] == "corr-request"


def test_call_policy_agent_prefers_request_correlation_id_over_payload(app, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["headers"] = headers
        return FakeResponse({"success": True, "policy_text": "generated"})

    monkeypatch.setattr(logic.requests, "post", fake_post)

    with app.test_request_context("/", headers={"X-Correlation-ID": "corr-request"}):
        app.preprocess_request()
        result = logic.call_policy_agent(
            {
                "context_id": "ctx-1",
                "correlation_id": "corr-payload",
                "refined_prompt": "prompt",
                "language": "en",
                "model_version": "0.1.0",
            }
        )

    assert result == {"success": True, "policy_text": "generated"}
    assert captured["headers"] == {"X-Correlation-ID": "corr-request"}


def test_call_policy_agent_emits_structured_logs(app_context, monkeypatch, caplog):
    def fake_post(url, json, headers, timeout):
        return FakeResponse({"success": True}, status_code=200)

    monkeypatch.setattr(logic.requests, "post", fake_post)

    with caplog.at_level("INFO"):
        result = logic.call_policy_agent(
            {
                "context_id": "ctx-log",
                "refined_prompt": "prompt",
                "language": "en",
                "model_version": "0.1.0",
            }
        )

    assert result == {"success": True}
    assert '"event": "context.policy.request"' in caplog.text
    assert '"event": "context.policy.response"' in caplog.text
    assert '"context_id": "ctx-log"' in caplog.text


def test_get_pipeline_diagnostic_returns_serialized_document(monkeypatch):
    fake_db = FakeDB(
        pipeline_diagnostics=[
            {
                "_id": ObjectId(),
                "correlation_id": "corr-1",
                "context_id": "ctx-1",
                "status": "completed",
                "hops": [],
            }
        ]
    )
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    result = logic.get_pipeline_diagnostic("corr-1")

    assert result["correlation_id"] == "corr-1"
    assert result["_id"]


def test_upsert_pipeline_diagnostic_bounds_hop_history(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(logic.mongo, "db", fake_db, raising=False)

    for index in range(logic.MAX_PIPELINE_DIAGNOSTIC_HOPS + 5):
        logic._upsert_pipeline_diagnostic(  # noqa: SLF001 - direct helper coverage
            correlation_id="corr-bounded",
            context_id="ctx-bounded",
            status="in_progress",
            hop={
                "service": "context-agent",
                "stage": "pipeline",
                "operation": f"step-{index}",
                "outcome": "success",
            },
        )

    diagnostic = fake_db.pipeline_diagnostics.find_one({"correlation_id": "corr-bounded"})

    assert len(diagnostic["hops"]) == logic.MAX_PIPELINE_DIAGNOSTIC_HOPS
    assert diagnostic["hops"][0]["operation"] == "step-5"
    assert diagnostic["hops"][-1]["operation"] == f"step-{logic.MAX_PIPELINE_DIAGNOSTIC_HOPS + 4}"


def test_pipeline_error_adds_request_correlation_id_when_exception_lacks_one(app, monkeypatch):
    with app.test_request_context("/", headers={"X-Correlation-ID": "corr-request"}):
        app.preprocess_request()
        result = logic._pipeline_error(  # noqa: SLF001 - direct helper coverage
            logic.PipelineStepError(
                stage="pipeline",
                message="failed",
                error_type="internal_error",
                error_code="unexpected_failure",
                status_code=500,
                details={},
            )
        )

    assert result["correlation_id"] == "corr-request"
