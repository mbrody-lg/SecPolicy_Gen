"""HTTP routes for context creation, iteration, and policy handoff."""

from datetime import datetime, timezone
import logging
import os

from bson import ObjectId
from flask import Blueprint, current_app, render_template, request, redirect, url_for, abort, flash, jsonify

from app import mongo
from app.metrics import metrics_response
from app.observability import log_event
from app.services.logic import (
    PipelineStepError,
    SECURITY_CONTEXT_VERSION,
    apply_context_building_answers,
    approve_context_intelligence_plan,
    build_context_building_state,
    build_context_security_context,
    build_context_intelligence_plan,
    context_plan_revision,
    context_answer_fields,
    get_health_status,
    get_system_status,
    get_pipeline_diagnostic,
    get_readiness_status,
    public_security_context_payload,
    refresh_system_state,
    generate_context_plan_prompt,
    run_with_agent,
    load_questions,
    render_markdown,
    synthesize_final_context,
    store_validated_policy,
)
from app.services.pipeline_jobs import (
    create_pipeline_job,
    find_active_pipeline_job,
    find_latest_pipeline_job,
    get_pipeline_job,
)
from app.services.pipeline_worker import start_pipeline_job_worker

main = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


def _pipeline_flash_message(result: dict) -> str:
    """Build a user-facing summary from a structured pipeline result."""
    stage = result.get("stage", "pipeline")
    message = result.get("message") or result.get("error") or "Policy pipeline failed."
    return f"{stage}: {message}"


POLICY_PROCESS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "policy_generating": "Generating policy",
    "policy_generated": "Policy generated",
    "validating": "Validating",
    "context_task_running": "Executing context plan",
    "context_task_completed": "Context plan executed",
    "completed": "Validated policy",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "not_started": "Not started",
}

POLICY_PROCESS_TONES = {
    "queued": "info",
    "running": "info",
    "policy_generating": "info",
    "policy_generated": "info",
    "validating": "info",
    "context_task_running": "info",
    "context_task_completed": "success",
    "completed": "success",
    "failed": "danger",
    "cancelled": "muted",
    "not_started": "muted",
}


@main.route("/health")
def health():
    """Expose a lightweight liveness probe."""
    return jsonify(get_health_status())


@main.route("/ready")
def ready():
    """Expose a minimal readiness probe for config and Mongo."""
    payload = get_readiness_status()
    status_code = 200 if payload.get("status") == "ready" else 503
    _log_readiness_response(payload, status_code)
    return jsonify(payload), status_code


@main.route("/metrics")
def metrics():
    """Expose Prometheus metrics for local observability."""
    return metrics_response()


def _log_readiness_response(payload: dict, status_code: int) -> None:
    """Emit a bounded structured event for readiness responses."""
    is_ready = payload.get("status") == "ready"
    log_event(
        logger,
        logging.INFO if is_ready else logging.WARNING,
        event="readiness.route.completed",
        stage="readiness",
        route="/ready",
        method="GET",
        status_code=status_code,
        result="success" if is_ready else "failure",
        readiness_status=payload.get("status", "unknown"),
        error_code=None if is_ready else "service_not_ready",
    )


@main.route("/system/status", methods=["GET"])
def system_status():
    """Return aggregated application readiness for the frontend."""
    payload = get_system_status()
    status_code = 200 if payload.get("status") == "ready" else 503
    return jsonify(payload), status_code


@main.route("/system/refresh", methods=["POST"])
def system_refresh():
    """Attempt controlled local maintenance actions and return to dashboard."""
    result = refresh_system_state()
    if _wants_json_response():
        return jsonify(result), 202 if result.get("success") else 503
    _flash_system_refresh_result(result)
    return redirect(url_for("main.index"))


def _wants_json_response() -> bool:
    """Detect progressive-enhancement requests from the operator UI."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def _flash_system_refresh_result(result: dict) -> None:
    """Flash a concise status message for controlled maintenance actions."""
    response = result.get("response", {})
    job = response.get("job") if isinstance(response, dict) else None
    if result.get("success") and result.get("status_code") == 202:
        job_status = job.get("status") if isinstance(job, dict) else "running"
        flash(f"System refresh started. Current job status: {job_status}.", "info")
    elif result.get("success"):
        flash("System state refreshed successfully.", "success")
    else:
        message = response.get("message") if isinstance(response, dict) else None
        message = message or result.get("message") or "System refresh did not complete."
        flash(message, "danger")


@main.route("/")
def index():
    """Render the context dashboard with filters, sort, and pagination."""
    per_page = 10
    page = max(int(request.args.get("page", 1)), 1)
    status_filter = request.args.get("status", "")
    sort_order = request.args.get("sort", "desc")

    query = {}
    if status_filter:
        query["status"] = status_filter

    sort_dir = -1 if sort_order == "desc" else 1
    sort_param = [("created_at", sort_dir)]

    fields = {
        "created_at": 1,
        "version": 1,
        "status": 1,
        "country": 1,
        "region": 1,
        "sector": 1,
        "generic": 1,
        "need": 1
    }

    collection = mongo.db.contexts
    total_count = collection.count_documents(query)
    contexts = list(
        collection.find(query, fields)
        .sort(sort_param)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    _attach_policy_process_summaries(contexts)

    return render_template(
        "dashboard.html",
        contexts=contexts,
        page=page,
        per_page=per_page,
        total_count=total_count,
        status_filter=status_filter,
        sort_order=sort_order,
        system_status=get_system_status(),
    )


def _attach_policy_process_summaries(contexts: list[dict]) -> None:
    """Add latest policy pipeline process state to dashboard context rows."""
    for context in contexts:
        context["policy_process"] = _policy_process_summary_for_job(
            find_latest_pipeline_job(str(context["_id"]))
        )


def _policy_process_summary_for_job(job: dict | None) -> dict:
    """Return a bounded dashboard summary for a policy pipeline job."""
    if not job:
        return {
            "status": "not_started",
            "label": POLICY_PROCESS_LABELS["not_started"],
            "tone": POLICY_PROCESS_TONES["not_started"],
        }

    status = job.get("status") or "unknown"
    summary = {
        "status": status,
        "label": POLICY_PROCESS_LABELS.get(status, status.replace("_", " ").title()),
        "tone": POLICY_PROCESS_TONES.get(status, "muted"),
        "stage": job.get("current_stage"),
        "correlation_id": job.get("correlation_id"),
        "diagnostic_url": _diagnostic_url_for_job(job),
    }
    last_error = job.get("last_error")
    if isinstance(last_error, dict):
        summary["error_code"] = last_error.get("error_code")
        summary["message"] = last_error.get("safe_message")
    return summary


def _diagnostic_url_for_job(job: dict) -> str | None:
    """Return a local development diagnostic URL for a pipeline job."""
    correlation_id = job.get("correlation_id")
    if not correlation_id or not _developer_diagnostics_enabled():
        return None
    return url_for("main.get_diagnostics", correlation_id=correlation_id)


def _developer_diagnostics_enabled() -> bool:
    """Return whether development-only diagnostic links should be displayed."""
    return bool(
        current_app.debug
        or current_app.testing
        or current_app.config.get("ENV") == "development"
        or os.getenv("FLASK_ENV") == "development"
    )


def _policy_generation_blocker(context: dict | None) -> dict | None:
    """Return the first domain reason that blocks policy generation."""
    if not context:
        return {
            "error_code": "context_not_found",
            "message": "Context not found.",
            "status_code": 404,
        }
    context_building = context.get("context_building")
    if isinstance(context_building, dict) and context_building.get("status") == "needs_information":
        return {
            "error_code": "context_building_needs_information",
            "message": "Answer the context-building questions before generating a policy.",
            "status_code": 409,
        }
    plan = context.get("context_intelligence_plan")
    if not isinstance(plan, dict):
        return {
            "error_code": "context_plan_not_available",
            "message": "Create and approve the context intelligence plan before generating a policy.",
            "status_code": 409,
        }
    if plan.get("status") != "approved":
        return {
            "error_code": "context_plan_not_approved",
            "message": "Approve the context intelligence plan before generating a policy.",
            "status_code": 409,
        }
    final_context = context.get("final_context")
    if (
        context.get("status") != "context_ready_for_policy"
        or not isinstance(final_context, dict)
        or final_context.get("context_ready_for_policy") is not True
    ):
        return {
            "error_code": "final_context_not_ready",
            "message": "Synthesize the final context before generating a policy.",
            "status_code": 409,
        }
    security_context = context.get("security_context")
    missing_information = []
    if isinstance(security_context, dict):
        missing_information = security_context.get("analysis", {}).get("missing_information", [])
    if not isinstance(security_context, dict) or missing_information:
        return {
            "error_code": "security_context_not_sufficient",
            "message": "Complete the security context before generating a policy.",
            "status_code": 409,
        }
    return None

@main.route("/create", methods=["GET", "POST"])
def create():
    """Create a new context and trigger the initial agent response."""
    if request.method == "POST":
        allowed_fields = context_answer_fields()
        data = {k: v.strip() for k, v in request.form.items() if k in allowed_fields}
        security_context = build_context_security_context(data)
        context_building = build_context_building_state(data, security_context=security_context)
        context_plan = build_context_intelligence_plan(data)

        initial_prompt = generate_context_plan_prompt(data)

        created_at = datetime.now(timezone.utc)

        inserted = mongo.db.contexts.insert_one({
            **data,
            "version": 1,
            "security_context_version": SECURITY_CONTEXT_VERSION,
            "security_context": security_context,
            "context_building": context_building,
            "context_intelligence_plan": context_plan,
            "status": (
                "context_building_needs_input"
                if context_building["status"] == "needs_information"
                else "planning"
            ),
            "created_at": created_at
        })

        context_id = inserted.inserted_id

        # Store questions and answers as separate agent/user interactions
        questions = load_questions()
        for q in questions:
            mongo.db.interactions.insert_one({
                "context_id": context_id,
                "question_id": f"q_{q['id']}",
                "question_text": q["question"],
                "answer": "",
                "timestamp": created_at,
                "origin": "agent"
            })
            mongo.db.interactions.insert_one({
                "context_id": context_id,
                "question_id": q["id"],
                "question_text": q["question"],
                "answer": data.get(q["id"]).strip() if data.get(q["id"]) else "",
                "timestamp": created_at,
                "origin": "user"
            })

        # Send prompt to the agent to generate refined context
        full_prompt = run_with_agent(
            initial_prompt,
            str(context_id),
            model_version="0.1.0",
        )

        if not full_prompt or not full_prompt.strip():
            flash("An initial response could not be generated. Please try again.", "warning")
            return redirect(url_for("main.context_detail", context_id=context_id))

        mongo.db.interactions.insert_one({
            "context_id": context_id,
            "question_id": "response_initial",
            "question_text": "Agent response",
            "answer": full_prompt.strip(),
            "timestamp": datetime.now(timezone.utc),
            "origin": "agent"
        })

        mongo.db.contexts.update_one(
            {"_id": context_id},
            {
                "$set": {
                    "status": (
                        "context_building_needs_input"
                        if context_building["status"] == "needs_information"
                        else "awaiting_task_validation"
                    )
                }
            }
        )

        return redirect(url_for("main.context_detail", context_id=context_id))

    questions = load_questions()
    return render_template(
        "create_context.html",
        questions=questions
    )

@main.route("/context/<context_id>")
def context_detail(context_id):
    """Render a context detail page with ordered interactions."""
    from bson.errors import InvalidId
    try:
        context_id = ObjectId(context_id)
        context = mongo.db.contexts.find_one({"_id": context_id})
        if not context:
            return abort(404, "Context not found.")

        interactions = list(
            mongo.db.interactions.find({"context_id": context_id}).sort("timestamp", 1)
        )
        # Render only agent answers to HTML from Markdown
        for item in interactions:
            if item.get("origin") == "agent" and item.get("answer"):
                item["rendered_answer"] = render_markdown(item["answer"])
            else:
                item["rendered_answer"] = item.get("answer", "")

    except (InvalidId, TypeError, Exception):
        return abort(400, "Invalid identifier.")

    return render_template(
        "context_detail.html",
        context=context,
        interactions=interactions,
        system_status=get_system_status(),
        latest_pipeline_job=find_latest_pipeline_job(str(context_id)),
        latest_context_plan_job=find_latest_pipeline_job(str(context_id), command="execute_context_plan"),
        developer_diagnostics_enabled=_developer_diagnostics_enabled(),
    )


@main.route("/context/<context_id>/security_context", methods=["GET"])
def get_security_context(context_id):
    """Return the structured security context for a stored context."""
    from bson.errors import InvalidId
    try:
        object_id = ObjectId(context_id)
    except (InvalidId, TypeError):
        return jsonify({
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_context_id",
            "message": "Invalid context_id format.",
            "details": {"context_id": context_id},
        }), 400

    context = mongo.db.contexts.find_one({"_id": object_id})
    if not context:
        return jsonify({
            "success": False,
            "error_type": "validation_error",
            "error_code": "context_not_found",
            "message": "Context not found.",
            "details": {"context_id": context_id},
        }), 404

    return jsonify(public_security_context_payload(context_id, context)), 200


@main.route("/context/<context_id>/context-plan", methods=["GET"])
def get_context_plan(context_id):
    """Return the public context-intelligence plan artifact."""
    from bson.errors import InvalidId
    try:
        object_id = ObjectId(context_id)
    except (InvalidId, TypeError):
        return jsonify({
            "success": False,
            "error_type": "contract_error",
            "error_code": "invalid_context_id",
            "message": "Invalid context_id format.",
            "details": {"context_id": context_id},
        }), 400

    context = mongo.db.contexts.find_one({"_id": object_id})
    if not context:
        return jsonify({
            "success": False,
            "error_type": "validation_error",
            "error_code": "context_not_found",
            "message": "Context not found.",
            "details": {"context_id": context_id},
        }), 404

    plan = context.get("context_intelligence_plan")
    if not isinstance(plan, dict):
        plan = build_context_intelligence_plan(context)
    return jsonify({
        "success": True,
        "context_id": context_id,
        "context_intelligence_plan": plan,
        "active_revision": context_plan_revision(plan),
    }), 200


@main.route("/context/<context_id>/context-building/answers", methods=["POST"])
def answer_context_building_questions(context_id):
    """Persist CONTEXT BUILDING answers and rebuild security-context artifacts."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return abort(404, "Context not found.")

    submitted_answers = _context_building_answers_from_request()
    if not submitted_answers:
        flash("Add at least one answer before updating the context.", "warning")
        return redirect(url_for("main.context_detail", context_id=context_id))

    result = apply_context_building_answers(context, submitted_answers)
    update_payload = {
        **result["answer_updates"],
        "status": result["status"],
        "security_context_version": SECURITY_CONTEXT_VERSION,
        "security_context": result["security_context"],
        "context_building": result["context_building"],
        "context_intelligence_plan": result["context_intelligence_plan"],
    }
    mongo.db.contexts.update_one({"_id": context_obj_id}, {"$set": update_payload})

    for question_id, answer in submitted_answers.items():
        if answer.strip():
            mongo.db.interactions.insert_one({
                "context_id": context_obj_id,
                "question_id": question_id,
                "question_text": "Context building answer",
                "answer": answer.strip(),
                "timestamp": datetime.now(timezone.utc),
                "origin": "user",
            })

    flash("Context building answers saved and security context updated.", "success")
    return redirect(url_for("main.context_detail", context_id=context_id))


def _context_building_answers_from_request() -> dict[str, str]:
    """Extract submitted CONTEXT BUILDING answers from form or JSON requests."""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        answers = payload.get("answers", payload)
        if isinstance(answers, dict):
            return {str(key): str(value) for key, value in answers.items()}
        return {}

    question_id = request.form.get("question_id")
    answer = request.form.get("answer")
    if question_id and answer is not None:
        return {question_id: answer}

    answers = {}
    for key, value in request.form.items():
        if key.startswith("answers[") and key.endswith("]"):
            answers[key.removeprefix("answers[").removesuffix("]")] = value
    return answers

@main.route("/context/<context_id>/continue", methods=["POST"])
def continue_context(context_id):
    """Append user input to an existing context and request next agent response."""
    context = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
    if not context:
        return abort(404, "Context not found.")

    new_prompt = request.form.get("prompt", "").strip()
    if not new_prompt:
        return redirect(url_for("main.context_detail", context_id=context_id))

    count = mongo.db.interactions.count_documents({
        "context_id": ObjectId(context_id),
        "question_id": {"$regex": "^need"}
    })
    new_question_id = f"need_{count + 1}"

    # 1. Save user interaction
    mongo.db.interactions.insert_one({
        "context_id": ObjectId(context_id),
        "question_id": new_question_id,
        "question_text": "Add more information or questions...",
        "answer": new_prompt,
        "timestamp": datetime.now(timezone.utc),
        "origin": "user"
    })

    # 2. Execute agent
    response = run_with_agent(
        new_prompt,
        context_id,
        model_version=context.get("version", "0.1.0"),
    )

    # 3. If no valid response exists, keep context pending and skip response save
    if not response or not response.strip():
        mongo.db.contexts.update_one(
            {"_id": ObjectId(context_id)},
            {"$set": {"status": "pending"}}
        )
        flash("A response could not be generated. Please try again.", "warning")
        return redirect(url_for("main.context_detail", context_id=context_id))

    # 4. Save agent response
    mongo.db.interactions.insert_one({
        "context_id": ObjectId(context_id),
        "question_id": f"response_{count + 1}",
        "question_text": "Agent response",
        "answer": response.strip(),
        "timestamp": datetime.now(timezone.utc),
        "origin": "agent"
    })

    security_context = build_context_security_context(
        context,
        additional_need=new_prompt,
    )
    updated_context_data = {
        **context,
        "need": security_context["policy_intent"]["need"] or context.get("need", ""),
    }
    context_building = build_context_building_state(
        updated_context_data,
        security_context=security_context,
        existing=context.get("context_building"),
    )
    context_plan = build_context_intelligence_plan(
        updated_context_data,
        existing_plan=context.get("context_intelligence_plan"),
    )

    mongo.db.contexts.update_one(
        {"_id": ObjectId(context_id)},
        {
            "$set": {
                "need": updated_context_data["need"],
                "status": (
                    "context_building_needs_input"
                    if context_building["status"] == "needs_information"
                    else "awaiting_task_validation"
                ),
                "security_context_version": SECURITY_CONTEXT_VERSION,
                "security_context": security_context,
                "context_building": context_building,
                "context_intelligence_plan": context_plan,
            }
        }
    )

    return redirect(url_for("main.context_detail", context_id=context_id))


@main.route("/context/<context_id>/context-plan/approve", methods=["POST"])
def approve_context_plan(context_id):
    """Approve the context-intelligence plan before task execution."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return abort(404, "Context not found.")
    context_building = context.get("context_building")
    if isinstance(context_building, dict) and context_building.get("status") == "needs_information":
        flash("Answer the context-building questions before approving the plan.", "warning")
        return redirect(url_for("main.context_detail", context_id=context_id))

    feedback = request.form.get("feedback", "")
    approved_plan = approve_context_intelligence_plan(context, feedback)
    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {
            "$set": {
                "status": "context_plan_approved",
                "context_intelligence_plan": approved_plan,
            }
        },
    )

    mongo.db.interactions.insert_one({
        "context_id": context_obj_id,
        "question_id": "context_plan_approved",
        "question_text": "Context intelligence plan approval",
        "answer": feedback.strip() or "Context intelligence plan approved.",
        "timestamp": datetime.now(timezone.utc),
        "origin": "user",
    })

    flash("Context intelligence plan approved. Task execution can start next.", "success")
    return redirect(url_for("main.context_detail", context_id=context_id))


@main.route("/context/<context_id>/context-plan/execute", methods=["POST"])
def trigger_context_plan_execution(context_id):
    """Start asynchronous execution of an approved context-intelligence plan."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return abort(404, "Context not found.")

    blocker = _context_plan_execution_blocker(context)
    if blocker:
        payload = {
            "success": False,
            "error_type": "workflow_error",
            "error_code": blocker["error_code"],
            "message": blocker["message"],
            "details": {"context_id": context_id},
        }
        if _wants_json_response():
            return jsonify(payload), blocker["status_code"]
        flash(payload["message"], "warning")
        return redirect(url_for("main.context_detail", context_id=context_id))

    active_job = find_active_pipeline_job(context_id, command="execute_context_plan")
    if active_job:
        payload = {
            "success": True,
            "status": "accepted",
            "message": "Context plan execution is already running.",
            "job": _public_pipeline_job(active_job),
        }
        if _wants_json_response():
            return jsonify(payload), 202
        flash("Context plan execution is already running.", "info")
        return redirect(url_for("main.context_detail", context_id=context_id))

    job = create_pipeline_job(
        context_id=context_id,
        command="execute_context_plan",
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    start_pipeline_job_worker(job)
    payload = {
        "success": True,
        "status": "accepted",
        "message": "Context plan execution started.",
        "job": _public_pipeline_job(job),
    }
    if _wants_json_response():
        return jsonify(payload), 202
    flash("Context plan execution started. Current stage: queued.", "info")
    return redirect(url_for("main.context_detail", context_id=context_id))


@main.route("/context/<context_id>/final-context/synthesize", methods=["POST"])
def trigger_final_context_synthesis(context_id):
    """Synthesize final context after approved plan execution."""
    result = synthesize_final_context(context_id)
    if _wants_json_response():
        return jsonify(result), 200 if result.get("success") else result.get("status_code", 500)
    if result.get("success"):
        flash("Final context synthesized. Policy generation is now available.", "success")
    else:
        flash(result.get("message", "Final context synthesis failed."), "warning")
    return redirect(url_for("main.context_detail", context_id=context_id))


def _context_plan_execution_blocker(context: dict) -> dict | None:
    """Return the first reason an approved context plan cannot execute."""
    context_building = context.get("context_building")
    if isinstance(context_building, dict) and context_building.get("status") == "needs_information":
        return {
            "error_code": "context_building_needs_information",
            "message": "Answer the context-building questions before executing the plan.",
            "status_code": 409,
        }
    plan = context.get("context_intelligence_plan")
    if not isinstance(plan, dict) or plan.get("status") != "approved":
        return {
            "error_code": "context_plan_not_approved",
            "message": "Approve the context intelligence plan before executing it.",
            "status_code": 409,
        }
    if not plan.get("approved_revision_id"):
        return {
            "error_code": "context_plan_revision_not_found",
            "message": "Approved context plan revision not found.",
            "status_code": 409,
        }
    return None

@main.route("/context/<context_id>/delete", methods=["POST"])
def delete_context(context_id):
    """Delete a context and its interaction history."""
    try:
        result = mongo.db.contexts.delete_one({"_id": ObjectId(context_id)})
        mongo.db.interactions.delete_many({"context_id": ObjectId(context_id)})
        if result.deleted_count == 1:
            flash("Context successfully removed.", "success")
        else:
            flash("The context could not be deleted.", "warning")
    except Exception:
        flash("Error deleting context.", "danger")

    return redirect(url_for("main.index"))

@main.route("/context/<context_id>/policy", methods=["POST"])
def send_policy_to_context(context_id):
    """Persist a validated policy payload in context interactions."""
    try:
        data = request.get_json(force=True) or {}
        store_validated_policy(context_id, data)
        return redirect(url_for("main.context_detail", context_id=context_id))
    except PipelineStepError as exc:
        correlation_id = request.headers.get("X-Correlation-ID") or context_id
        return jsonify({
            "success": False,
            "error_type": exc.error_type,
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "correlation_id": correlation_id,
        }), exc.status_code
    except Exception:
        correlation_id = request.headers.get("X-Correlation-ID") or context_id
        return jsonify({
            "success": False,
            "error_type": "internal_error",
            "error_code": "policy_callback_failed",
            "message": "An internal error has occurred.",
            "details": {"context_id": context_id},
            "correlation_id": correlation_id,
        }), 500


@main.route("/context/<context_id>/generate_policy", methods=["POST"])
def trigger_policy_generation(context_id):
    """Start end-to-end policy generation and validation for a context."""
    context = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
    blocker = _policy_generation_blocker(context)
    if blocker:
        payload = {
            "success": False,
            "error_type": "workflow_error",
            "error_code": blocker["error_code"],
            "message": blocker["message"],
            "details": {"context_id": context_id},
        }
        if _wants_json_response():
            return jsonify(payload), blocker["status_code"]
        flash(payload["message"], "warning")
        return redirect(url_for("main.context_detail", context_id=context_id))

    system_status = get_system_status()
    if system_status.get("status") != "ready":
        payload = {
            "success": False,
            "error_type": "readiness_error",
            "error_code": "runtime_not_ready",
            "message": "Application runtime is not ready. Update state before generating a policy.",
            "details": {"context_id": context_id},
        }
        if _wants_json_response():
            return jsonify(payload), 503
        flash(payload["message"], "danger")
        return redirect(url_for("main.context_detail", context_id=context_id))

    active_job = find_active_pipeline_job(context_id)
    if active_job:
        payload = {
            "success": True,
            "status": "accepted",
            "message": "Policy generation is already running.",
            "job": _public_pipeline_job(active_job),
        }
        if _wants_json_response():
            return jsonify(payload), 202
        flash(
            f"Policy generation is already running. Current stage: {active_job['current_stage']}.",
            "info",
        )
        return redirect(url_for("main.context_detail", context_id=context_id))

    job = create_pipeline_job(
        context_id=context_id,
        command="generate_policy",
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    start_pipeline_job_worker(job)
    payload = {
        "success": True,
        "status": "accepted",
        "message": "Policy generation started.",
        "job": _public_pipeline_job(job),
    }
    if _wants_json_response():
        return jsonify(payload), 202
    flash("Policy generation started. Current stage: queued.", "info")
    return redirect(url_for("main.context_detail", context_id=context_id))


@main.route("/context/<context_id>/system/refresh", methods=["POST"])
def context_system_refresh(context_id):
    """Attempt controlled local maintenance actions and return to the context detail."""
    result = refresh_system_state()
    if _wants_json_response():
        return jsonify(result), 202 if result.get("success") else 503
    _flash_system_refresh_result(result)
    return redirect(url_for("main.context_detail", context_id=context_id))


def _public_pipeline_diagnostic(diagnostic: dict) -> dict:
    """Return the public allowlisted diagnostic view for operator lookup."""
    allowed_top_level = {
        "correlation_id",
        "context_id",
        "status",
        "created_at",
        "updated_at",
        "completed_at",
    }
    allowed_hop_fields = {
        "service",
        "stage",
        "operation",
        "target_service",
        "outcome",
        "started_at",
        "completed_at",
        "duration_ms",
        "status_code",
        "error_type",
        "error_code",
        "validation_status",
    }
    allowed_error_fields = {"stage", "error_type", "error_code"}

    public = {
        key: diagnostic[key]
        for key in allowed_top_level
        if key in diagnostic and diagnostic[key] is not None
    }
    public["hops"] = [
        {
            key: hop[key]
            for key in allowed_hop_fields
            if isinstance(hop, dict) and key in hop and hop[key] is not None
        }
        for hop in diagnostic.get("hops", [])
        if isinstance(hop, dict)
    ]
    last_error = diagnostic.get("last_error")
    if isinstance(last_error, dict):
        public["last_error"] = {
            key: last_error[key]
            for key in allowed_error_fields
            if key in last_error and last_error[key] is not None
        }
    return public


def _public_pipeline_job(job: dict) -> dict:
    """Return the public allowlisted pipeline job view."""
    allowed_top_level = {
        "job_id",
        "context_id",
        "correlation_id",
        "command",
        "status",
        "current_stage",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "result_refs",
    }
    allowed_error_fields = {
        "failed_stage",
        "error_type",
        "error_code",
        "safe_message",
        "status_code",
    }
    public = {
        key: job[key]
        for key in allowed_top_level
        if key in job and job[key] is not None
    }
    last_error = job.get("last_error")
    if isinstance(last_error, dict):
        public["last_error"] = {
            key: last_error[key]
            for key in allowed_error_fields
            if key in last_error and last_error[key] is not None
        }
    diagnostic_url = _diagnostic_url_for_job(public)
    if diagnostic_url:
        public["diagnostic_url"] = diagnostic_url
    return public


@main.route("/pipeline/jobs/<job_id>", methods=["GET"])
def get_pipeline_job_status(job_id):
    """Return a bounded pipeline job status document."""
    job = get_pipeline_job(job_id)
    if not job:
        return jsonify({
            "success": False,
            "error_type": "validation_error",
            "error_code": "pipeline_job_not_found",
            "message": "Pipeline job not found.",
            "details": {"job_id": job_id},
        }), 404
    return jsonify({"success": True, "job": _public_pipeline_job(job)}), 200


@main.route("/context/<context_id>/pipeline/jobs/active", methods=["GET"])
def get_active_pipeline_job_status(context_id):
    """Return the active pipeline job for a context when one exists."""
    job = find_active_pipeline_job(context_id)
    if not job:
        return jsonify({
            "success": False,
            "error_type": "validation_error",
            "error_code": "active_pipeline_job_not_found",
            "message": "Active pipeline job not found.",
            "details": {"context_id": context_id},
        }), 404
    return jsonify({"success": True, "job": _public_pipeline_job(job)}), 200


@main.route("/diagnostics/<correlation_id>", methods=["GET"])
def get_diagnostics(correlation_id):
    """Return a bounded pipeline diagnostic document by correlation id."""
    diagnostic = get_pipeline_diagnostic(correlation_id)
    if not diagnostic:
        return jsonify({
            "success": False,
            "error_type": "validation_error",
            "error_code": "diagnostic_not_found",
            "message": "Pipeline diagnostic not found.",
            "details": {"correlation_id": correlation_id},
            "correlation_id": correlation_id,
        }), 404
    return jsonify(_public_pipeline_diagnostic(diagnostic)), 200
