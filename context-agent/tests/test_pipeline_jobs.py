from types import SimpleNamespace

import pytest

from app.services import pipeline_jobs


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query):
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
    def __init__(self, pipeline_jobs_docs=None, pipeline_events_docs=None):
        self.pipeline_jobs = FakeCollection(pipeline_jobs_docs)
        self.pipeline_events = FakeCollection(pipeline_events_docs)


def test_create_pipeline_job_persists_job_and_initial_event(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        command="generate_policy",
        correlation_id="corr-1",
    )

    assert job["context_id"] == "ctx-1"
    assert job["correlation_id"] == "corr-1"
    assert job["command"] == "generate_policy"
    assert job["status"] == "queued"
    assert job["current_stage"] == "queued"
    assert job["ownership"]["source_of_truth"] is True
    assert len(fake_db.pipeline_jobs.docs) == 1
    assert len(fake_db.pipeline_events.docs) == 1
    event = fake_db.pipeline_events.docs[0]
    assert event["event_type"] == "job_created"
    assert event["job_id"] == job["job_id"]
    assert event["ownership"]["source_of_truth"] is False


def test_find_active_pipeline_job_ignores_terminal_jobs(monkeypatch):
    fake_db = FakeDB(
        pipeline_jobs_docs=[
            {
                "job_id": "job-completed",
                "context_id": "ctx-1",
                "command": "generate_policy",
                "status": "completed",
            },
            {
                "job_id": "job-active",
                "context_id": "ctx-1",
                "command": "generate_policy",
                "status": "policy_generating",
            },
        ]
    )
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    job = pipeline_jobs.find_active_pipeline_job("ctx-1")

    assert job["job_id"] == "job-active"


def test_update_pipeline_job_state_records_event_and_sanitizes_error(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        command="generate_policy",
        correlation_id="corr-1",
    )

    updated = pipeline_jobs.update_pipeline_job_state(
        job_id=job["job_id"],
        status="failed",
        stage="policy_generation",
        error={
            "stage": "policy_generation",
            "error_type": "dependency_error",
            "error_code": "policy_agent_timeout",
            "safe_message": "Policy generation timed out.",
            "raw_exception": "HTTPConnectionPool(host='policy-agent', port=5000)",
            "prompt": "raw user prompt",
            "provider_payload": {"secret": "value"},
        },
    )

    assert updated["status"] == "failed"
    assert updated["current_stage"] == "policy_generation"
    assert updated["last_error"] == {
        "error_type": "dependency_error",
        "error_code": "policy_agent_timeout",
        "safe_message": "Policy generation timed out.",
        "failed_stage": "policy_generation",
    }
    assert "completed_at" in updated
    assert len(fake_db.pipeline_events.docs) == 2
    event = fake_db.pipeline_events.docs[-1]
    assert event["event_type"] == "job_status_changed"
    assert event["error"] == updated["last_error"]
    assert "raw_exception" not in event["error"]
    assert "prompt" not in event["error"]
    assert "provider_payload" not in event["error"]


def test_update_pipeline_job_state_rejects_unknown_status(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    with pytest.raises(ValueError, match="Unsupported pipeline job status"):
        pipeline_jobs.update_pipeline_job_state(job_id="job-1", status="sleeping")
