"""Pipeline job state and event contracts for long-running context workflows."""

from datetime import datetime, timezone
from uuid import uuid4

from flask import current_app, has_app_context

from app import get_request_correlation_id, mongo
from app.metrics import record_pipeline_job_transition

DEFAULT_PIPELINE_JOB_STALE_AFTER_SECONDS = 1800

PIPELINE_JOB_STATUSES = frozenset(
    {
        "queued",
        "running",
        "policy_generating",
        "policy_generated",
        "validating",
        "completed",
        "failed",
        "cancelled",
    }
)
PIPELINE_JOB_ACTIVE_STATUSES = frozenset(
    {
        "queued",
        "running",
        "policy_generating",
        "policy_generated",
        "validating",
    }
)
PIPELINE_JOB_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
PIPELINE_JOB_ERROR_FIELDS = frozenset(
    {"failed_stage", "stage", "error_type", "error_code", "safe_message", "status_code"}
)


def _pipeline_jobs_collection():
    """Return the collection used as source of truth for pipeline execution."""
    return mongo.db.pipeline_jobs


def _pipeline_events_collection():
    """Return the append-only collection used for pipeline stage events."""
    return mongo.db.pipeline_events


def _serialize_pipeline_document(document: dict | None) -> dict | None:
    """Return a JSON-safe pipeline document without mutating the stored value."""
    if not document:
        return None
    serialized = dict(document)
    if "_id" in serialized:
        serialized["_id"] = str(serialized["_id"])
    for field in ("created_at", "updated_at", "started_at", "completed_at"):
        if field in serialized and hasattr(serialized[field], "isoformat"):
            serialized[field] = serialized[field].isoformat()
    return serialized


def _sanitize_pipeline_error(error: dict | None) -> dict | None:
    """Allow only bounded operational error fields in persisted job state."""
    if not error:
        return None
    sanitized = {
        key: value
        for key, value in error.items()
        if key in PIPELINE_JOB_ERROR_FIELDS and value is not None
    }
    if "stage" in sanitized and "failed_stage" not in sanitized:
        sanitized["failed_stage"] = sanitized.pop("stage")
    if sanitized.get("safe_message"):
        sanitized["safe_message"] = str(sanitized["safe_message"])[:240]
    return sanitized or None


def append_pipeline_event(
    *,
    job_id: str,
    context_id: str,
    correlation_id: str,
    event_type: str,
    status: str,
    stage: str,
    error: dict | None = None,
) -> dict:
    """Persist one append-only pipeline event with bounded operational fields."""
    now = datetime.now(timezone.utc)
    event = {
        "_id": str(uuid4()),
        "job_id": job_id,
        "context_id": context_id,
        "correlation_id": correlation_id,
        "event_type": event_type,
        "status": status,
        "stage": stage,
        "created_at": now,
        "ownership": {
            "owner_service": "context-agent",
            "source_of_truth": False,
            "collection": "pipeline_events",
            "view_type": "pipeline_event",
        },
    }
    safe_error = _sanitize_pipeline_error(error)
    if safe_error:
        event["error"] = safe_error
    _pipeline_events_collection().insert_one(event)
    return event


def create_pipeline_job(
    *,
    context_id: str,
    command: str = "generate_policy",
    correlation_id: str | None = None,
) -> dict:
    """Create a queued pipeline job and its first append-only event."""
    now = datetime.now(timezone.utc)
    job_id = str(uuid4())
    resolved_correlation_id = correlation_id or get_request_correlation_id() or str(uuid4())
    job = {
        "_id": job_id,
        "job_id": job_id,
        "context_id": str(context_id),
        "correlation_id": resolved_correlation_id,
        "command": command,
        "status": "queued",
        "current_stage": "queued",
        "created_at": now,
        "updated_at": now,
        "ownership": {
            "owner_service": "context-agent",
            "source_of_truth": True,
            "collection": "pipeline_jobs",
            "view_type": "pipeline_job",
        },
        "result_refs": {},
    }
    _pipeline_jobs_collection().insert_one(job)
    append_pipeline_event(
        job_id=job_id,
        context_id=str(context_id),
        correlation_id=resolved_correlation_id,
        event_type="job_created",
        status="queued",
        stage="queued",
    )
    record_pipeline_job_transition(status="queued", stage="queued")
    return _serialize_pipeline_document(job)


def find_active_pipeline_job(context_id: str, *, command: str = "generate_policy") -> dict | None:
    """Return the active job for a context/command when one is still running."""
    query = {
        "context_id": str(context_id),
        "command": command,
        "status": {"$in": sorted(PIPELINE_JOB_ACTIVE_STATUSES)},
    }
    for _ in range(10):
        job = _pipeline_jobs_collection().find_one(query)
        if not job:
            return None
        if not _is_pipeline_job_stale(job):
            return _serialize_pipeline_document(job)
        _mark_pipeline_job_stale(job)
    return None


def get_pipeline_job(job_id: str) -> dict | None:
    """Return a pipeline job by id."""
    job = _pipeline_jobs_collection().find_one({"job_id": job_id})
    if job and job.get("status") in PIPELINE_JOB_ACTIVE_STATUSES and _is_pipeline_job_stale(job):
        return _mark_pipeline_job_stale(job)
    return _serialize_pipeline_document(job)


def update_pipeline_job_state(
    *,
    job_id: str,
    status: str,
    stage: str | None = None,
    error: dict | None = None,
    result_refs: dict | None = None,
) -> dict | None:
    """Persist a pipeline job transition and append the matching event."""
    if status not in PIPELINE_JOB_STATUSES:
        raise ValueError(f"Unsupported pipeline job status: {status}")

    existing = _pipeline_jobs_collection().find_one({"job_id": job_id})
    if not existing:
        return None

    now = datetime.now(timezone.utc)
    current_stage = stage or status
    set_fields = {
        "status": status,
        "current_stage": current_stage,
        "updated_at": now,
    }
    if status != "queued" and not existing.get("started_at"):
        set_fields["started_at"] = now
    if status in PIPELINE_JOB_TERMINAL_STATUSES:
        set_fields["completed_at"] = now
    if result_refs is not None:
        set_fields["result_refs"] = result_refs
    safe_error = _sanitize_pipeline_error(error)
    if safe_error:
        set_fields["last_error"] = safe_error

    _pipeline_jobs_collection().update_one({"job_id": job_id}, {"$set": set_fields})
    append_pipeline_event(
        job_id=job_id,
        context_id=existing["context_id"],
        correlation_id=existing["correlation_id"],
        event_type="job_status_changed",
        status=status,
        stage=current_stage,
        error=safe_error,
    )
    record_pipeline_job_transition(
        status=status,
        stage=current_stage,
        error_code=(safe_error or {}).get("error_code"),
        duration_seconds=_pipeline_duration_seconds(existing, now)
        if status in PIPELINE_JOB_TERMINAL_STATUSES
        else None,
    )
    return get_pipeline_job(job_id)


def _pipeline_duration_seconds(existing: dict, completed_at: datetime) -> float | None:
    """Return bounded terminal duration from started_at or created_at."""
    started_at = existing.get("started_at") or existing.get("created_at")
    if not started_at or not hasattr(started_at, "timestamp"):
        return None
    return (_ensure_utc_datetime(completed_at) - _ensure_utc_datetime(started_at)).total_seconds()


def _ensure_utc_datetime(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime for Mongo values that may be naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mark_pipeline_job_stale(job: dict) -> dict | None:
    """Move one stale active pipeline job to a bounded terminal failure."""
    stage = job.get("current_stage", "pipeline")
    return update_pipeline_job_state(
        job_id=job["job_id"],
        status="failed",
        stage=stage,
        error={
            "stage": stage,
            "error_type": "runtime_error",
            "error_code": "pipeline_job_stale",
            "safe_message": "Policy pipeline job expired before reaching a terminal state.",
            "status_code": 504,
        },
    )


def _is_pipeline_job_stale(job: dict, *, now: datetime | None = None) -> bool:
    """Return whether an active job has exceeded the runtime stale threshold."""
    reference_time = job.get("updated_at") or job.get("started_at") or job.get("created_at")
    if not reference_time or not hasattr(reference_time, "timestamp"):
        return False
    current_time = now or datetime.now(timezone.utc)
    reference_time = _ensure_utc_datetime(reference_time)
    current_time = _ensure_utc_datetime(current_time)
    return (current_time - reference_time).total_seconds() > _pipeline_job_stale_after_seconds()


def _pipeline_job_stale_after_seconds() -> float:
    """Read the stale-job threshold from app config when available."""
    if has_app_context():
        return float(
            current_app.config.get(
                "PIPELINE_JOB_STALE_AFTER_SECONDS",
                DEFAULT_PIPELINE_JOB_STALE_AFTER_SECONDS,
            )
        )
    return float(DEFAULT_PIPELINE_JOB_STALE_AFTER_SECONDS)
