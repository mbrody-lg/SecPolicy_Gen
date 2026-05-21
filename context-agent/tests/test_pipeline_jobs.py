from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

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

    def find(self, query):
        return FakeCursor(
            doc for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        )

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


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction):
        self.docs.sort(key=lambda doc: doc.get(key), reverse=direction == -1)
        return self

    def limit(self, limit):
        self.docs = self.docs[:limit]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeDB:
    def __init__(self, pipeline_jobs_docs=None, pipeline_events_docs=None):
        self.pipeline_jobs = FakeCollection(pipeline_jobs_docs)
        self.pipeline_events = FakeCollection(pipeline_events_docs)


def test_create_pipeline_job_persists_job_and_initial_event(monkeypatch):
    fake_db = FakeDB()
    captured_metrics = []
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        pipeline_jobs,
        "record_pipeline_job_transition",
        lambda **kwargs: captured_metrics.append(kwargs),
    )

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
    assert job["progress"] == {
        "current": 0,
        "total": 0,
        "percent": 0,
        "current_task_id": None,
        "current_task_title": None,
        "completed_task_ids": [],
        "last_message": "Queued.",
    }
    assert job["ownership"]["source_of_truth"] is True
    assert len(fake_db.pipeline_jobs.docs) == 1
    assert len(fake_db.pipeline_events.docs) == 1
    event = fake_db.pipeline_events.docs[0]
    assert event["event_type"] == "job_created"
    assert event["job_id"] == job["job_id"]
    assert event["ownership"]["source_of_truth"] is False
    assert captured_metrics == [
        {
            "status": "queued",
            "stage": "queued",
        }
    ]


def test_create_pipeline_job_accepts_execute_context_plan_command(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        pipeline_jobs,
        "record_pipeline_job_transition",
        lambda **kwargs: None,
    )

    job = pipeline_jobs.create_pipeline_job(
        context_id="ctx-1",
        command="execute_context_plan",
        correlation_id="corr-1",
    )

    assert job["command"] == "execute_context_plan"
    assert fake_db.pipeline_events.docs[0]["status"] == "queued"


def test_update_pipeline_job_progress_persists_public_progress_event_and_metrics(monkeypatch):
    fake_db = FakeDB(
        pipeline_jobs_docs=[
            {
                "job_id": "job-1",
                "context_id": "ctx-1",
                "correlation_id": "corr-1",
                "command": "execute_context_plan",
                "status": "context_task_running",
                "current_stage": "context_plan_execution",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]
    )
    captured_metrics = []
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        pipeline_jobs,
        "record_pipeline_job_transition",
        lambda **kwargs: captured_metrics.append(kwargs),
    )

    job = pipeline_jobs.update_pipeline_job_progress(
        job_id="job-1",
        status="context_task_running",
        stage="context_plan_execution",
        current=2,
        total=8,
        current_task_id="identity_access",
        current_task_title="Identity, access, and device posture",
        completed_task_ids=["company_profile", "information_assets"],
        last_message="Completed task 2 of 8.",
        event_type="context_task_completed",
    )

    assert job["progress"] == {
        "current": 2,
        "total": 8,
        "percent": 25,
        "current_task_id": "identity_access",
        "current_task_title": "Identity, access, and device posture",
        "completed_task_ids": ["company_profile", "information_assets"],
        "last_message": "Completed task 2 of 8.",
    }
    assert job["updated_at"]
    event = fake_db.pipeline_events.docs[0]
    assert event["event_type"] == "context_task_completed"
    assert event["progress"]["percent"] == 25
    assert captured_metrics[-1] == {
        "status": "context_task_running",
        "stage": "context_plan_execution",
    }


def test_list_pipeline_events_returns_recent_events(monkeypatch):
    now = datetime.now(timezone.utc)
    fake_db = FakeDB(
        pipeline_events_docs=[
            {"job_id": "job-1", "event_type": "old", "created_at": now - timedelta(seconds=2)},
            {"job_id": "job-2", "event_type": "other", "created_at": now - timedelta(seconds=1)},
            {"job_id": "job-1", "event_type": "new", "created_at": now},
        ]
    )
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    events = pipeline_jobs.list_pipeline_events("job-1", limit=2)

    assert [event["event_type"] for event in events] == ["new", "old"]


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


def test_find_active_pipeline_job_scopes_by_command(monkeypatch):
    fake_db = FakeDB(
        pipeline_jobs_docs=[
            {
                "job_id": "job-policy",
                "context_id": "ctx-1",
                "command": "generate_policy",
                "status": "policy_generating",
            },
            {
                "job_id": "job-context-plan",
                "context_id": "ctx-1",
                "command": "execute_context_plan",
                "status": "context_task_running",
            },
        ]
    )
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    job = pipeline_jobs.find_active_pipeline_job("ctx-1", command="execute_context_plan")

    assert job["job_id"] == "job-context-plan"


def test_find_active_pipeline_job_marks_stale_job_failed(monkeypatch):
    old_updated_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    fake_db = FakeDB(
        pipeline_jobs_docs=[
            {
                "job_id": "job-stale",
                "context_id": "ctx-1",
                "correlation_id": "corr-1",
                "command": "generate_policy",
                "status": "policy_generating",
                "current_stage": "policy_generation",
                "created_at": old_updated_at,
                "updated_at": old_updated_at,
            }
        ]
    )
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(pipeline_jobs, "_pipeline_job_stale_after_seconds", lambda: 60.0)

    job = pipeline_jobs.find_active_pipeline_job("ctx-1")

    assert job is None
    stale_job = fake_db.pipeline_jobs.docs[0]
    assert stale_job["status"] == "failed"
    assert stale_job["current_stage"] == "policy_generation"
    assert stale_job["last_error"] == {
        "error_type": "runtime_error",
        "error_code": "pipeline_job_stale",
        "safe_message": "Policy pipeline job expired before reaching a terminal state.",
        "status_code": 504,
        "failed_stage": "policy_generation",
    }
    assert fake_db.pipeline_events.docs[-1]["status"] == "failed"
    assert fake_db.pipeline_events.docs[-1]["error"]["error_code"] == "pipeline_job_stale"


def test_get_pipeline_job_marks_stale_active_job_failed(monkeypatch):
    old_updated_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    fake_db = FakeDB(
        pipeline_jobs_docs=[
            {
                "job_id": "job-stale",
                "context_id": "ctx-1",
                "correlation_id": "corr-1",
                "command": "generate_policy",
                "status": "running",
                "current_stage": "pipeline",
                "created_at": old_updated_at,
                "updated_at": old_updated_at,
            }
        ]
    )
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(pipeline_jobs, "_pipeline_job_stale_after_seconds", lambda: 60.0)

    job = pipeline_jobs.get_pipeline_job("job-stale")

    assert job["status"] == "failed"
    assert job["last_error"]["error_code"] == "pipeline_job_stale"


def test_update_pipeline_job_state_records_event_and_sanitizes_error(monkeypatch):
    fake_db = FakeDB()
    captured_metrics = []
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        pipeline_jobs,
        "record_pipeline_job_transition",
        lambda **kwargs: captured_metrics.append(kwargs),
    )
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
    assert captured_metrics[-1]["status"] == "failed"
    assert captured_metrics[-1]["stage"] == "policy_generation"
    assert captured_metrics[-1]["error_code"] == "policy_agent_timeout"
    assert captured_metrics[-1]["duration_seconds"] >= 0


def test_update_pipeline_job_state_handles_naive_started_at(monkeypatch):
    created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    fake_db = FakeDB(
        pipeline_jobs_docs=[
            {
                "job_id": "job-naive-start",
                "context_id": "ctx-1",
                "correlation_id": "corr-1",
                "command": "generate_policy",
                "status": "policy_generating",
                "current_stage": "policy_generation",
                "created_at": created_at,
                "updated_at": created_at,
                "started_at": datetime.utcnow() - timedelta(seconds=5),
            }
        ]
    )
    captured_metrics = []
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)
    monkeypatch.setattr(
        pipeline_jobs,
        "record_pipeline_job_transition",
        lambda **kwargs: captured_metrics.append(kwargs),
    )

    updated = pipeline_jobs.update_pipeline_job_state(
        job_id="job-naive-start",
        status="failed",
        stage="policy_generation",
        error={
            "stage": "policy_generation",
            "error_code": "policy_agent_timeout",
            "safe_message": "Policy generation timed out.",
        },
    )

    assert updated["status"] == "failed"
    assert captured_metrics[-1]["status"] == "failed"
    assert captured_metrics[-1]["duration_seconds"] >= 0


def test_update_pipeline_job_state_rejects_unknown_status(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(pipeline_jobs.mongo, "db", fake_db, raising=False)

    with pytest.raises(ValueError, match="Unsupported pipeline job status"):
        pipeline_jobs.update_pipeline_job_state(job_id="job-1", status="sleeping")
