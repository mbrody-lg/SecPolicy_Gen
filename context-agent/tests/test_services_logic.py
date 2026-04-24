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

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._payload


def test_get_context_and_prompt_prefers_context_refined_prompt(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[
            {
                "_id": context_id,
                "refined_prompt": "canonical refined prompt",
                "language": "es",
                "version": "1.2.3",
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


def test_get_context_and_prompt_falls_back_to_legacy_interaction(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[{"_id": context_id, "language": "en", "version": "0.2.0"}],
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


def test_get_context_and_prompt_normalizes_numeric_model_version(monkeypatch):
    context_id = ObjectId()
    fake_db = FakeDB(
        contexts=[{"_id": context_id, "refined_prompt": "prompt", "language": "en", "version": 1}],
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
        contexts=[{"_id": context_id, "refined_prompt": "prompt", "language": "en", "version": "0.2.0"}],
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
