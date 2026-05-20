from types import SimpleNamespace

import pytest

from test_base import *
from app.services import pipeline_jobs, pipeline_worker


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

    def update_one(self, query, update):
        target = self.find_one(query)
        if target is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        for key, value in update.get("$set", {}).items():
            target[key] = value
        return SimpleNamespace(matched_count=1, modified_count=1)


class FakeDB:
    def __init__(self):
        self.pipeline_jobs = FakeCollection()
        self.pipeline_events = FakeCollection()


def test_run_pipeline_job_completes_successful_pipeline(app, monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        correlation_id="corr-1",
    )
    captured = {}

    def fake_generate_full_policy_pipeline(context_id):
        captured["context_id"] = context_id
        return {
            "success": True,
            "stage": "completed",
            "persistence": {
                "context_id": context_id,
                "interaction_id": "interaction-1",
            },
            "validated_data": {"status": "accepted"},
        }

    monkeypatch.setattr(
        pipeline_worker.logic,
        "generate_full_policy_pipeline",
        fake_generate_full_policy_pipeline,
    )

    updated = pipeline_worker.run_pipeline_job(app=app, job_id=job["job_id"])

    assert captured["context_id"] == "ctx-1"
    assert updated["status"] == "completed"
    assert updated["current_stage"] == "completed"
    assert updated["result_refs"] == {
        "context_id": "ctx-1",
        "validated_interaction_id": "interaction-1",
        "validation_status": "accepted",
    }
    assert [event["status"] for event in fake_db.pipeline_events.docs] == [
        "queued",
        "running",
        "policy_generating",
        "completed",
    ]


def test_run_pipeline_job_persists_bounded_failure(app, monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        correlation_id="corr-1",
    )
    monkeypatch.setattr(
        pipeline_worker.logic,
        "generate_full_policy_pipeline",
        lambda context_id: {
            "success": False,
            "stage": "policy_generation",
            "error_type": "dependency_error",
            "error_code": "policy_agent_timeout",
            "message": "Policy generation timed out.",
            "details": {
                "raw_exception": "HTTPConnectionPool(host='policy-agent', port=5000)",
                "prompt": "raw prompt",
            },
            "status_code": 502,
        },
    )

    updated = pipeline_worker.run_pipeline_job(app=app, job_id=job["job_id"])

    assert updated["status"] == "failed"
    assert updated["current_stage"] == "policy_generation"
    assert updated["last_error"] == {
        "error_type": "dependency_error",
        "error_code": "policy_agent_timeout",
        "safe_message": "Policy generation timed out.",
        "status_code": 502,
        "failed_stage": "policy_generation",
    }
    terminal_event = fake_db.pipeline_events.docs[-1]
    assert terminal_event["status"] == "failed"
    assert "raw_exception" not in terminal_event["error"]
    assert "prompt" not in terminal_event["error"]


def test_run_pipeline_job_dispatches_execute_context_plan_command(app, monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        command="execute_context_plan",
        correlation_id="corr-1",
    )
    captured = {}
    def fake_execute_context_plan(context_id):
        captured["context_id"] = context_id
        return {
            "success": True,
            "stage": "context_plan_execution",
            "context_id": context_id,
            "plan_revision_id": "plan-rev-1",
            "task_count": 2,
        }

    monkeypatch.setattr(
        pipeline_worker.logic,
        "execute_context_plan",
        fake_execute_context_plan,
    )
    monkeypatch.setattr(
        pipeline_worker.logic,
        "generate_full_policy_pipeline",
        lambda context_id: pytest.fail("must not run policy pipeline"),
    )

    updated = pipeline_worker.run_pipeline_job(app=app, job_id=job["job_id"])

    assert captured["context_id"] == "ctx-1"
    assert updated["status"] == "completed"
    assert updated["current_stage"] == "context_plan_completed"
    assert updated["result_refs"] == {
        "context_id": "ctx-1",
        "plan_revision_id": "plan-rev-1",
        "task_count": 2,
    }
    assert [event["status"] for event in fake_db.pipeline_events.docs] == [
        "queued",
        "running",
        "context_task_running",
        "completed",
    ]


def test_run_pipeline_job_persists_safe_context_plan_failure(app, monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        command="execute_context_plan",
        correlation_id="corr-1",
    )
    monkeypatch.setattr(
        pipeline_worker.logic,
        "execute_context_plan",
        lambda context_id: {
            "success": False,
            "stage": "context_plan_execution",
            "error_type": "workflow_error",
            "error_code": "context_task_execution_failed",
            "message": "Context plan task execution failed.",
            "details": {"raw_exception": "must not leak"},
            "status_code": 502,
        },
    )

    updated = pipeline_worker.run_pipeline_job(app=app, job_id=job["job_id"])

    assert updated["status"] == "failed"
    assert updated["current_stage"] == "context_plan_execution"
    assert updated["last_error"] == {
        "error_type": "workflow_error",
        "error_code": "context_task_execution_failed",
        "safe_message": "Context plan task execution failed.",
        "status_code": 502,
        "failed_stage": "context_plan_execution",
    }
    assert "raw_exception" not in fake_db.pipeline_events.docs[-1]["error"]


def test_run_pipeline_job_rejects_unknown_command(app, monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        command="unknown",
        correlation_id="corr-1",
    )
    monkeypatch.setattr(
        pipeline_worker.logic,
        "generate_full_policy_pipeline",
        lambda context_id: pytest.fail("must not run policy pipeline"),
    )
    monkeypatch.setattr(
        pipeline_worker.logic,
        "execute_context_plan",
        lambda context_id: pytest.fail("must not run context plan"),
    )

    updated = pipeline_worker.run_pipeline_job(app=app, job_id=job["job_id"])

    assert updated["status"] == "failed"
    assert updated["last_error"]["error_code"] == "unsupported_pipeline_command"


def test_run_pipeline_job_returns_none_for_missing_job(app, monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    assert pipeline_worker.run_pipeline_job(app=app, job_id="missing") is None
