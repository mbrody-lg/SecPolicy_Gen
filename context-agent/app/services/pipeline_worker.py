"""Worker entrypoints for asynchronous policy pipeline jobs."""

from threading import Thread

from flask import current_app

from app import CORRELATION_ID_HEADER
from app.services import logic, pipeline_jobs


def start_pipeline_job_worker(job: dict) -> dict:
    """Start a background worker for a queued pipeline job."""
    app = current_app._get_current_object()
    thread = Thread(
        target=run_pipeline_job,
        kwargs={"app": app, "job_id": job["job_id"]},
        daemon=True,
    )
    thread.start()
    return {"started": True, "job_id": job["job_id"]}


def run_pipeline_job(*, app, job_id: str) -> dict | None:
    """Execute one pipeline job and persist terminal state."""
    with app.app_context():
        job = pipeline_jobs.get_pipeline_job(job_id)
        if not job:
            return None

        pipeline_jobs.update_pipeline_job_state(
            job_id=job_id,
            status="running",
            stage="pipeline",
        )
        if job.get("command") == "execute_context_plan":
            return _run_context_plan_job(app, job_id, job)
        if job.get("command") != "generate_policy":
            return pipeline_jobs.update_pipeline_job_state(
                job_id=job_id,
                status="failed",
                stage="pipeline",
                error={
                    "stage": "pipeline",
                    "error_type": "contract_error",
                    "error_code": "unsupported_pipeline_command",
                    "safe_message": "Unsupported pipeline command.",
                    "status_code": 400,
                },
            )

        pipeline_jobs.update_pipeline_job_state(
            job_id=job_id,
            status="policy_generating",
            stage="policy_generation",
        )
        result = _execute_pipeline_with_correlation(app, job)
        if result.get("success"):
            return pipeline_jobs.update_pipeline_job_state(
                job_id=job_id,
                status="completed",
                stage="completed",
                result_refs=_result_refs(result),
            )

        return pipeline_jobs.update_pipeline_job_state(
            job_id=job_id,
            status="failed",
            stage=result.get("stage", "pipeline"),
            error={
                "stage": result.get("stage", "pipeline"),
                "error_type": result.get("error_type", "internal_error"),
                "error_code": result.get("error_code", "policy_pipeline_failed"),
                "safe_message": result.get("message") or result.get("error") or "Policy pipeline failed.",
                "status_code": result.get("status_code"),
            },
        )


def _execute_pipeline_with_correlation(app, job: dict) -> dict:
    """Run the existing pipeline under the job correlation id."""
    headers = {CORRELATION_ID_HEADER: job["correlation_id"]}
    with app.test_request_context("/", headers=headers):
        app.preprocess_request()
    return logic.generate_full_policy_pipeline(job["context_id"])


def _run_context_plan_job(app, job_id: str, job: dict) -> dict | None:
    """Execute an approved context plan under the job correlation id."""
    pipeline_jobs.update_pipeline_job_state(
        job_id=job_id,
        status="context_task_running",
        stage="context_plan_execution",
    )
    headers = {CORRELATION_ID_HEADER: job["correlation_id"]}
    with app.test_request_context("/", headers=headers):
        app.preprocess_request()
        result = logic.execute_context_plan(
            job["context_id"],
            on_task_progress=_context_plan_progress_callback(job_id),
        )

    if result.get("success"):
        return pipeline_jobs.update_pipeline_job_state(
            job_id=job_id,
            status="completed",
            stage="context_plan_completed",
            result_refs={
                "context_id": result.get("context_id"),
                "plan_revision_id": result.get("plan_revision_id"),
                "task_count": result.get("task_count"),
            },
        )

    return pipeline_jobs.update_pipeline_job_state(
        job_id=job_id,
        status="failed",
        stage=result.get("stage", "context_plan_execution"),
        error={
            "stage": result.get("stage", "context_plan_execution"),
            "error_type": result.get("error_type", "workflow_error"),
            "error_code": result.get("error_code", "context_plan_execution_failed"),
            "safe_message": result.get("message") or "Context plan execution failed.",
            "status_code": result.get("status_code"),
        },
    )


def _context_plan_progress_callback(job_id: str):
    """Return a callback that mirrors context plan task progress to the job."""
    def _callback(progress: dict) -> None:
        pipeline_jobs.update_pipeline_job_progress(
            job_id=job_id,
            status="context_task_running",
            stage=progress.get("stage", "context_plan_execution"),
            current=progress.get("current", 0),
            total=progress.get("total", 0),
            current_task_id=progress.get("current_task_id"),
            current_task_title=progress.get("current_task_title"),
            completed_task_ids=progress.get("completed_task_ids") or [],
            last_message=progress.get("last_message"),
            event_type=progress.get("event_type", "context_task_progress"),
        )

    return _callback


def _result_refs(result: dict) -> dict:
    """Extract stable result references without duplicating domain payloads."""
    refs = {}
    persistence = result.get("persistence")
    if isinstance(persistence, dict):
        if persistence.get("context_id"):
            refs["context_id"] = persistence["context_id"]
        if persistence.get("interaction_id"):
            refs["validated_interaction_id"] = persistence["interaction_id"]
    validated_data = result.get("validated_data")
    if isinstance(validated_data, dict) and validated_data.get("status"):
        refs["validation_status"] = validated_data["status"]
    return refs
