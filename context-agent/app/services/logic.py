"""Service helpers for context prompting and policy pipeline orchestration."""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from time import perf_counter
from uuid import uuid4

import requests
import yaml
from bson import ObjectId
from flask import current_app, has_app_context
from markdown import markdown

from app import (
    CORRELATION_ID_HEADER,
    DEFAULT_CONFIG_PATH,
    DEFAULT_QUESTIONS_CONFIG_PATH,
    get_request_correlation_id,
    mongo,
)
from app.context_output_schemas import context_phase_output_schema
from app.agents.factory import create_agent_from_config
from app.context_analysis import SECURITY_CONTEXT_VERSION, build_security_context_from_answers
from app.context_analysis import security_context_to_business_context
from app.observability import build_log_event, log_event

logger = logging.getLogger(__name__)
MAX_PIPELINE_DIAGNOSTIC_HOPS = 25
SYSTEM_STATUS_TIMEOUT_SECONDS = 2.0
SYSTEM_RAG_STATUS_TIMEOUT_SECONDS = 10.0
DEFAULT_CONTEXT_PROMPT_TEMPLATES = {
    "context_intake": "\n".join([
        "You are Context Agent working inside the Context Workplace.",
        "Phase: INTAKE / NEW CONTEXT.",
        "Your task is to transform the user's company answers into a detailed, concrete, security-focused company context.",
        "Do not draft the final policy. Produce a refined context that downstream Policy Agent and RAG retrieval can use.",
        "",
        "Security context analysis:",
        "{security_context_summary}",
        "",
        "User-provided answers:",
        "{user_answers}",
        "",
        "Output requirements: write a concise but complete business and information-security context; identify the security domains, relevant assets, data categories, regulatory exposure, assumptions, missing information, and the concrete policy objective.",
    ]),
    "context_update": "\n".join([
        "You are Context Agent working inside the Context Workplace.",
        "Phase: CONTEXT UPDATE.",
        "The user has added new context or answered follow-up questions. Re-assess the case without losing prior facts.",
        "",
        "New user input:",
        "{additional_context}",
        "",
        "Current security context analysis:",
        "{security_context_summary}",
        "",
        "Existing case facts:",
        "{user_answers}",
        "",
        "Output requirements: explain what changed, preserve explicit facts, identify remaining gaps as actionable follow-up questions. Do not draft a policy. Do not approve the plan.",
    ]),
    "context_planning": "\n".join([
        "You are Context Agent working inside the Context Workplace.",
        "Phase: PLANNING.",
        "Produce a reviewable analysis plan that lists the tasks needed to reach a complete security context.",
        "Ask the user to confirm whether this plan is appropriate or whether relevant business, IT, risk, or compliance aspects are missing.",
        "",
        "Initial security context:",
        "{security_context_summary}",
        "",
        "Proposed context-intelligence tasks:",
        "{context_tasks}",
        "",
        "User-provided answers:",
        "{user_answers}",
        "",
        "Output requirements: explain the proposed tasks, identify any missing task, and end by asking the user to approve the plan or add more context before execution.",
    ]),
    "context_task_execution": "\n".join([
        "You are Context Agent working inside the Context Workplace.",
        "Phase: EXECUTION.",
        "Execute one approved context-intelligence task. Do not generate a policy. Produce only task analysis for final context synthesis.",
        "",
        "Task:",
        "{task_summary}",
        "",
        "Approved plan revision:",
        "{plan_revision_summary}",
        "",
        "Current security context:",
        "{security_context_summary}",
        "",
        "Output requirements: return concise, concrete findings, assumptions, missing details, and implications for final company security context synthesis.",
    ]),
    "policy_handoff": "\n".join([
        "Final company security context for Policy Agent.",
        "This is the approved handoff artifact, not a conversation transcript.",
        "",
        "Final context metadata:",
        "{final_context_metadata}",
        "",
        "Approved sections:",
        "{final_context_sections}",
    ]),
}
CONTEXT_ANSWER_FIELDS = {
    "country",
    "region",
    "sector",
    "company_activity",
    "company_size",
    "business_model",
    "service_type",
    "important_assets",
    "critical_assets",
    "data_categories",
    "third_party_dependencies",
    "cloud_services",
    "current_security_operations",
    "known_gaps",
    "methodology",
    "regulatory_hints",
    "security_maturity",
    "risk_tolerance",
    "governance_owner",
    "generic",
    "policy_type",
    "policy_scope",
    "policy_exclusions",
    "policy_audience",
    "need",
    "language",
}
CONTEXT_INTELLIGENCE_PLAN_VERSION = "1.0"
CONTEXT_BUILDING_VERSION = "1.0"
CONTEXT_TASK_RESULTS_VERSION = "1.0"
FINAL_CONTEXT_VERSION = "1.0"
CONTEXT_BUILDING_QUESTION_MAP = {
    "profile.sector": {
        "answer_field": "sector",
        "question": "Which business sector should the security context use?",
        "rationale": "Sector determines relevant threats, regulatory expectations, and RAG collection priorities.",
    },
    "profile.operating_countries": {
        "answer_field": "country",
        "question": "In which country should legal and regulatory analysis be anchored?",
        "rationale": "Jurisdiction is required before mapping legal obligations and sector norms.",
    },
    "information_assets.critical_assets": {
        "answer_field": "critical_assets",
        "question": "Which information assets are critical for business continuity or risk exposure?",
        "rationale": "Critical assets define the protection scope and the policy controls that matter most.",
    },
    "policy_intent.need": {
        "answer_field": "need",
        "question": "What concrete security need should this context and later policy generation cover?",
        "rationale": "Policy generation must be tied to an explicit business and security objective.",
    },
}
CONTEXT_INTELLIGENCE_TASKS = (
    {
        "id": "company_profile",
        "title": "Company profile and operating model",
        "objective": "Clarify the business activity, locations, service model, scale, ownership, and operational constraints that shape the security plan.",
    },
    {
        "id": "information_assets",
        "title": "Information assets and data exposure",
        "objective": "Identify critical systems, data categories, confidentiality needs, integrity requirements, and business continuity dependencies.",
    },
    {
        "id": "identity_access",
        "title": "Identity, access, and device posture",
        "objective": "Review account lifecycle, privileged access, MFA, remote access, endpoints, shared devices, and administrative responsibilities.",
    },
    {
        "id": "third_parties_cloud",
        "title": "Third-party, SaaS, and cloud dependencies",
        "objective": "Map providers, SaaS platforms, outsourced operations, supplier risks, data processor exposure, and dependency criticality.",
    },
    {
        "id": "regulatory_methodology",
        "title": "Regulatory, sector, and methodology fit",
        "objective": "Determine applicable legal obligations, sector expectations, contractual requirements, and practical control frameworks.",
    },
    {
        "id": "resilience_incidents",
        "title": "Resilience, backups, incidents, and known gaps",
        "objective": "Assess existing controls, backup and recovery evidence, incident readiness, known weaknesses, and risk tolerance.",
    },
    {
        "id": "policy_intent_rag",
        "title": "Policy objective and RAG retrieval strategy",
        "objective": "Define policy type, scope, audience, exclusions, required evidence families, and downstream Policy Agent context needs.",
    },
    {
        "id": "final_synthesis",
        "title": "Final security context synthesis",
        "objective": "Combine validated task outputs into a complete final context with assumptions, missing information, and retrieval hints.",
    },
)


class PipelineStepError(Exception):
    """Structured pipeline error used to keep orchestration failures explicit."""

    def __init__(
        self,
        *,
        stage: str,
        message: str,
        error_type: str,
        error_code: str,
        status_code: int,
        details: dict | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.error_type = error_type
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        self.correlation_id = correlation_id


def get_health_status() -> dict:
    """Return a lightweight liveness payload without touching dependencies."""
    return {
        "status": "ok",
        "service": "context-agent",
    }


def _required_readiness_config() -> dict[str, str]:
    """Return the minimal config keys needed for this service to operate safely."""
    return {
        "SECRET_KEY": current_app.config.get("SECRET_KEY"),
        "MONGO_URI": current_app.config.get("MONGO_URI"),
    }


def _config_readiness_check() -> dict:
    """Validate essential runtime configuration."""
    missing = sorted(
        key for key, value in _required_readiness_config().items()
        if value is None or str(value).strip() == ""
    )
    return {
        "status": "ok" if not missing else "error",
        "missing": missing,
    }


def _mongo_readiness_check() -> dict:
    """Validate MongoDB connectivity with a safe ping."""
    try:
        mongo.cx.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        return {
            "status": "error",
            "reason": "ping_failed",
        }


def get_readiness_status() -> dict:
    """Return service readiness based on essential config and Mongo reachability."""
    config_check = _config_readiness_check()
    mongo_check = _mongo_readiness_check()
    checks = {
        "config": config_check,
        "mongo": mongo_check,
    }
    is_ready = all(check["status"] == "ok" for check in checks.values())
    return {
        "status": "ready" if is_ready else "not_ready",
        "service": "context-agent",
        "checks": checks,
    }


def _service_endpoint_status(name: str, base_url: str, *, path: str = "/ready") -> dict:
    """Return bounded service status from a dependency endpoint."""
    timeout_seconds = (
        SYSTEM_RAG_STATUS_TIMEOUT_SECONDS
        if path == "/rag/status"
        else SYSTEM_STATUS_TIMEOUT_SECONDS
    )
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}{path}",
            timeout=timeout_seconds,
        )
        payload = response.json() if response.content else {}
    except requests.RequestException:
        return {
            "service": name,
            "status": "unreachable",
            "status_code": None,
            "checks": {},
        }
    except ValueError:
        return {
            "service": name,
            "status": "error",
            "status_code": response.status_code,
            "checks": {},
        }

    return {
        "service": name,
        "status": payload.get("status", "unknown") if isinstance(payload, dict) else "unknown",
        "status_code": response.status_code,
        "checks": payload.get("checks", {}) if isinstance(payload, dict) else {},
        "payload": payload if isinstance(payload, dict) else {},
    }


def get_system_status() -> dict:
    """Aggregate local service readiness and RAG runtime status for the UI."""
    context_status = get_readiness_status()
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    validator_agent_url = current_app.config.get("VALIDATOR_AGENT_URL", "http://validator-agent:5000")

    services = [
        {
            "service": "context-agent",
            "status": context_status.get("status", "unknown"),
            "status_code": 200 if context_status.get("status") == "ready" else 503,
            "checks": context_status.get("checks", {}),
        },
        _service_endpoint_status("policy-agent", policy_agent_url),
        _service_endpoint_status("validator-agent", validator_agent_url),
    ]
    rag_status = _service_endpoint_status("policy-agent-rag", policy_agent_url, path="/rag/status")
    all_ready = all(service.get("status") == "ready" for service in services)
    rag_ready = rag_status.get("payload", {}).get("rag", {}).get("status") == "ready"
    rag_payload = rag_status.get("payload", {}).get("rag", {
        "status": rag_status.get("status", "unknown"),
        "reason": "rag_status_unavailable",
    })

    return {
        "status": "ready" if all_ready and rag_ready else "not_ready",
        "services": services,
        "rag": rag_payload,
        "actions": {
            "rag_refresh_available": bool(rag_payload.get("refresh_available", False)),
            "rag_refresh_path": "/system/refresh",
        },
    }


def refresh_system_state() -> dict:
    """Attempt a controlled dependency refresh and return the updated system status."""
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    correlation_id = _get_correlation_id() or str(uuid4())
    log_event(
        logger,
        logging.INFO,
        event="context.system_refresh.request",
        stage="rag_refresh",
        correlation_id=correlation_id,
        target_service="policy-agent",
        operation="rag_refresh",
    )
    try:
        response = requests.post(
            f"{policy_agent_url.rstrip('/')}/rag/refresh",
            headers={CORRELATION_ID_HEADER: correlation_id} if correlation_id else {},
            timeout=_dependency_timeout("POLICY_AGENT_TIMEOUT_SECONDS"),
        )
        payload = response.json() if response.content else {}
    except requests.RequestException:
        log_event(
            logger,
            logging.WARNING,
            event="context.system_refresh.response",
            stage="rag_refresh",
            correlation_id=correlation_id,
            target_service="policy-agent",
            operation="rag_refresh",
            result="failure",
            error_code="policy_agent_unreachable",
        )
        return {
            "success": False,
            "error_code": "policy_agent_unreachable",
            "message": "Policy agent is unreachable.",
            "status": get_system_status(),
        }
    except ValueError:
        log_event(
            logger,
            logging.WARNING,
            event="context.system_refresh.response",
            stage="rag_refresh",
            correlation_id=correlation_id,
            target_service="policy-agent",
            operation="rag_refresh",
            result="failure",
            status_code=response.status_code,
            error_code="invalid_policy_agent_response",
        )
        return {
            "success": False,
            "error_code": "invalid_policy_agent_response",
            "message": "Policy agent returned an invalid response.",
            "status": get_system_status(),
        }

    result = "success" if response.status_code < 400 and payload.get("success") is True else "failure"
    log_event(
        logger,
        logging.INFO if result == "success" else logging.WARNING,
        event="context.system_refresh.response",
        stage="rag_refresh",
        correlation_id=correlation_id,
        target_service="policy-agent",
        operation="rag_refresh",
        status_code=response.status_code,
        result=result,
        refresh_status=payload.get("job", {}).get("status"),
        error_code=payload.get("error_code"),
    )
    return {
        "success": response.status_code < 400 and payload.get("success") is True,
        "status_code": response.status_code,
        "response": payload,
        "status": get_system_status(),
    }


def _resolve_config_path(config_key: str, env_name: str, default_path: str) -> str:
    """Resolve runtime config paths from Flask config, environment, or defaults."""
    if has_app_context():
        return current_app.config.get(config_key, default_path)
    return os.getenv(env_name, default_path)


def _agent_config_path() -> str:
    return _resolve_config_path("CONFIG_PATH", "CONFIG_PATH", DEFAULT_CONFIG_PATH)


def _questions_config_path() -> str:
    return _resolve_config_path(
        "QUESTIONS_CONFIG_PATH",
        "QUESTIONS_CONFIG_PATH",
        DEFAULT_QUESTIONS_CONFIG_PATH,
    )


def load_questions(config_path: str | None = None):
    """Load context-question definitions from YAML configuration."""
    resolved_config_path = config_path or _questions_config_path()
    with open(resolved_config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]


def load_context_prompt_templates(config_path: str | None = None) -> dict[str, str]:
    """Load phase-specific Context Workplace prompt templates from YAML config."""
    resolved_config_path = config_path or _agent_config_path()
    try:
        with open(resolved_config_path, "r", encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
    except OSError:
        return dict(DEFAULT_CONTEXT_PROMPT_TEMPLATES)
    templates = payload.get("prompts") if isinstance(payload, dict) else None
    merged = dict(DEFAULT_CONTEXT_PROMPT_TEMPLATES)
    if isinstance(templates, dict):
        for key, value in templates.items():
            if isinstance(value, str) and value.strip():
                merged[str(key)] = value.strip()
    return merged


class _SafePromptValues(dict):
    def __missing__(self, key):
        return "unknown"


def _render_context_prompt_template(template_name: str, values: dict[str, str]) -> str:
    template = load_context_prompt_templates().get(
        template_name,
        DEFAULT_CONTEXT_PROMPT_TEMPLATES[template_name],
    )
    return template.format_map(_SafePromptValues(values)).strip()


def context_answer_fields(question_config: str | None = None) -> set[str]:
    """Return supported context answer ids from configured questions plus legacy fields."""
    try:
        configured = {str(question["id"]) for question in load_questions(question_config)}
    except Exception:
        configured = set()
    return CONTEXT_ANSWER_FIELDS.union(configured)


def _security_context_prompt_summary(security_context: dict) -> str:
    return "\n".join([
        f"- Version: {security_context['version']}",
        f"- Sector: {security_context['profile']['sector'] or 'unknown'}",
        f"- Activity: {security_context['profile']['activity'] or 'unknown'}",
        f"- Countries: {_format_list(security_context['profile']['operating_countries'])}",
        f"- Region: {security_context['profile']['region'] or 'unknown'}",
        f"- Important assets: {_format_list(security_context['information_assets']['important_assets'])}",
        f"- Critical assets: {_format_list(security_context['information_assets']['critical_assets'])}",
        f"- Data categories: {_format_list(security_context['information_assets']['data_categories'])}",
        f"- Third-party dependencies: {_format_list(security_context['information_assets']['third_party_dependencies'])}",
        f"- Cloud/SaaS services: {_format_list(security_context['information_assets']['cloud_services'])}",
        f"- Current controls: {_format_list(security_context['security_posture']['current_controls'])}",
        f"- Known gaps: {_format_list(security_context['security_posture']['known_gaps'])}",
        f"- Regulatory hints: {_format_list(security_context['compliance']['regulatory_hints'])}",
        f"- Methodologies: {_format_list(security_context['compliance']['methodologies'])}",
        f"- Policy need: {security_context['policy_intent']['need'] or 'unknown'}",
        f"- Policy type: {security_context['policy_intent']['policy_type'] or 'unknown'}",
        f"- Scope: {security_context['policy_intent']['scope'] or 'unknown'}",
        f"- Audience: {security_context['policy_intent']['audience'] or 'unknown'}",
        f"- Specificity: {security_context['policy_intent']['specificity'] or 'unknown'}",
        f"- Missing information: {_format_list(security_context['analysis']['missing_information'])}",
        f"- Retrieval collection hints: {_format_list(security_context['retrieval_hints']['collection_families'])}",
    ])


def _user_answers_prompt_summary(data: dict, question_config: str | None = None) -> str:
    lines = []
    for q in load_questions(question_config):
        key = q["id"]
        answer = str(data.get(key, "") or "").strip()
        if answer:
            lines.append(f"- {q['question']} {answer}")
    return "\n".join(lines) if lines else "- No explicit answers available."


def generate_context_prompt(data: dict, question_config: str | None = None) -> str:
    """
    Build a text prompt from form answers.
    This prompt is used to drive context generation.
    """
    security_context = build_context_security_context(data)

    return _render_context_prompt_template(
        "context_intake",
        {
            "security_context_summary": _security_context_prompt_summary(security_context),
            "user_answers": _user_answers_prompt_summary(data, question_config),
        },
    )


def build_context_intelligence_plan(context_data: dict, existing_plan: dict | None = None) -> dict:
    """Build the reviewable multi-task plan for context intelligence work."""
    security_context = build_context_security_context(context_data)
    existing_revisions = []
    if isinstance(existing_plan, dict):
        existing_revisions = [
            dict(revision)
            for revision in existing_plan.get("revisions", [])
            if isinstance(revision, dict)
        ]
    tasks = []
    for index, task in enumerate(CONTEXT_INTELLIGENCE_TASKS, start=1):
        tasks.append({
            "id": task["id"],
            "order": index,
            "title": task["title"],
            "objective": task["objective"],
            "status": "planned",
            "result": None,
        })

    return {
        "version": CONTEXT_INTELLIGENCE_PLAN_VERSION,
        "status": "draft",
        "tasks": tasks,
        "review": {
            "required": True,
            "user_feedback": None,
            "approved_at": None,
            "approved_by": None,
            "approval_source": None,
            "approval_notes": None,
            "context_snapshot_hash": None,
        },
        "approved_revision_id": None,
        "revisions": existing_revisions,
        "context_snapshot": {
            "sector": security_context["profile"]["sector"],
            "activity": security_context["profile"]["activity"],
            "critical_assets": security_context["information_assets"]["critical_assets"],
            "data_categories": security_context["information_assets"]["data_categories"],
            "missing_information": security_context["analysis"]["missing_information"],
            "retrieval_collection_families": security_context["retrieval_hints"]["collection_families"],
        },
    }


def build_context_building_state(
    context_data: dict,
    *,
    security_context: dict | None = None,
    existing: dict | None = None,
    bypassed: bool = False,
) -> dict:
    """Build the embedded CONTEXT BUILDING artifact for a context record."""
    security_context = security_context or build_context_security_context(context_data)
    existing_questions = {}
    if isinstance(existing, dict):
        existing_questions = {
            question.get("field_path"): dict(question)
            for question in existing.get("questions", [])
            if isinstance(question, dict) and question.get("field_path")
        }

    missing_information = list(security_context["analysis"]["missing_information"])
    questions = []
    for field_path in missing_information:
        question = _context_building_question(field_path, existing_questions.get(field_path))
        if question:
            questions.append(question)

    for field_path, question in existing_questions.items():
        if field_path not in missing_information and question.get("status") == "answered":
            questions.append(question)

    status = "approved" if bypassed else "sufficient"
    if not bypassed and any(question["status"] in {"pending", "deferred"} for question in questions):
        status = "needs_information"

    return {
        "version": CONTEXT_BUILDING_VERSION,
        "status": status,
        "bypassed": bypassed,
        "missing_information": missing_information,
        "questions": questions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def apply_context_building_answers(context: dict, submitted_answers: dict[str, str]) -> dict:
    """Apply user answers to CONTEXT BUILDING questions and rebuild artifacts."""
    context_building = context.get("context_building") or build_context_building_state(context)
    questions = context_building.get("questions", [])
    if not isinstance(questions, list):
        questions = []

    answer_updates = {}
    answered_questions = []
    for question in questions:
        question_id = str(question.get("id", ""))
        answer = str(submitted_answers.get(question_id, "") or "").strip()
        if not answer:
            answered_questions.append(question)
            continue
        answer_field = question.get("answer_field")
        if answer_field in CONTEXT_ANSWER_FIELDS:
            answer_updates[answer_field] = answer
            answered = dict(question)
            answered["status"] = "answered"
            answered["answer"] = answer
            answered["answered_at"] = datetime.now(timezone.utc).isoformat()
            answered_questions.append(answered)
        else:
            answered_questions.append(question)

    updated_context = {**context, **answer_updates}
    security_context = build_context_security_context(updated_context)
    updated_building = build_context_building_state(
        updated_context,
        security_context=security_context,
        existing={**context_building, "questions": answered_questions},
    )
    context_plan = build_context_intelligence_plan(
        updated_context,
        existing_plan=context.get("context_intelligence_plan"),
    )
    status = (
        "context_building_needs_input"
        if updated_building["status"] == "needs_information"
        else "awaiting_task_validation"
    )
    return {
        "answer_updates": answer_updates,
        "security_context": security_context,
        "context_building": updated_building,
        "context_intelligence_plan": context_plan,
        "status": status,
    }


def defer_context_building_question(context: dict, question_id: str, reason: str | None = None) -> dict:
    """Mark a CONTEXT BUILDING question as deferred without unlocking planning."""
    context_building = context.get("context_building") or build_context_building_state(context)
    questions = context_building.get("questions", [])
    if not isinstance(questions, list):
        questions = []

    now = datetime.now(timezone.utc).isoformat()
    updated_questions = []
    deferred = None
    for question in questions:
        if str(question.get("id", "")) != str(question_id):
            updated_questions.append(question)
            continue
        deferred = dict(question)
        deferred["status"] = "deferred"
        deferred["deferred_at"] = now
        deferred["deferred_reason"] = str(reason or "").strip() or None
        updated_questions.append(deferred)

    if not deferred:
        return {
            "success": False,
            "error_type": "validation_error",
            "error_code": "context_building_question_not_found",
            "message": "Context-building question not found.",
            "status_code": 404,
        }

    updated_building = {
        **context_building,
        "status": "needs_information",
        "questions": updated_questions,
        "updated_at": now,
    }
    return {
        "success": True,
        "context_building": updated_building,
        "status": "context_building_needs_input",
        "deferred_question": deferred,
    }


def _context_building_question(field_path: str, existing: dict | None = None) -> dict | None:
    definition = CONTEXT_BUILDING_QUESTION_MAP.get(field_path)
    if not definition:
        return None
    question_id = f"context_building_{field_path.replace('.', '_')}"
    question = {
        "id": question_id,
        "field_path": field_path,
        "answer_field": definition["answer_field"],
        "question": definition["question"],
        "rationale": definition["rationale"],
        "status": "pending",
        "answer": None,
        "source": "security_context.analysis.missing_information",
    }
    if existing:
        question.update({
            key: existing[key]
            for key in ("status", "answer", "answered_at", "deferred_at", "deferred_reason")
            if key in existing
        })
    if question.get("answer") and question.get("status") == "pending":
        question["status"] = "answered"
    return question


def _context_tasks_prompt_summary(plan: dict) -> str:
    lines = []
    for task in plan.get("tasks", []):
        lines.append(f"{task['order']}. {task['title']}: {task['objective']}")
    return "\n".join(lines) if lines else "- No context-intelligence tasks available."


def generate_context_plan_prompt(data: dict, question_config: str | None = None) -> str:
    """Build the initial prompt that asks the agent to review the task plan."""
    security_context = build_context_security_context(data)
    plan = build_context_intelligence_plan(data)

    return _render_context_prompt_template(
        "context_planning",
        {
            "security_context_summary": _security_context_prompt_summary(security_context),
            "context_tasks": _context_tasks_prompt_summary(plan),
            "user_answers": _user_answers_prompt_summary(data, question_config),
        },
    )


def generate_context_update_prompt(context: dict, additional_context: str) -> str:
    """Build the prompt used when Intake adds more context after creation."""
    updated_context = {**context, "need": additional_context or context.get("need", "")}
    security_context = build_context_security_context(
        context,
        additional_need=additional_context,
    )
    return _render_context_prompt_template(
        "context_update",
        {
            "additional_context": additional_context,
            "security_context_summary": _security_context_prompt_summary(security_context),
            "user_answers": _user_answers_prompt_summary(updated_context),
        },
    )


def approve_context_intelligence_plan(
    context: dict,
    feedback: str | None = None,
    *,
    approved_by: str = "user",
    approval_source: str = "ui",
) -> dict:
    """Return an approved copy of the persisted context-intelligence plan."""
    plan = context.get("context_intelligence_plan")
    if not isinstance(plan, dict):
        plan = build_context_intelligence_plan(context)

    approved = dict(plan)
    revisions = [
        dict(revision)
        for revision in approved.get("revisions", [])
        if isinstance(revision, dict)
    ]
    revision_id = f"plan-rev-{len(revisions) + 1}"
    approved_at = datetime.now(timezone.utc).isoformat()
    context_snapshot_hash = _context_snapshot_hash(approved.get("context_snapshot", {}))
    approved["status"] = "approved"
    approved["approved_revision_id"] = revision_id
    approved["revisions"] = revisions + [
        {
            "revision_id": revision_id,
            "status": "approved",
            "approved_at": approved_at,
            "approved_by": approved_by,
            "approval_source": approval_source,
            "approval_notes": (feedback or "").strip() or None,
            "context_snapshot_hash": context_snapshot_hash,
            "context_snapshot": dict(approved.get("context_snapshot") or {}),
            "tasks": [dict(task) for task in approved.get("tasks", [])],
        }
    ]
    approved["review"] = dict(approved.get("review") or {})
    approved["review"]["required"] = False
    approved["review"]["user_feedback"] = (feedback or "").strip() or None
    approved["review"]["approval_notes"] = (feedback or "").strip() or None
    approved["review"]["approved_at"] = approved_at
    approved["review"]["approved_by"] = approved_by
    approved["review"]["approval_source"] = approval_source
    approved["review"]["context_snapshot_hash"] = context_snapshot_hash
    approved["tasks"] = [
        {**task, "status": "approved" if task.get("status") == "planned" else task.get("status", "approved")}
        for task in approved.get("tasks", [])
    ]
    return approved


def context_plan_revision(plan: dict) -> dict | None:
    """Return the active immutable plan revision, when one exists."""
    if not isinstance(plan, dict):
        return None
    approved_revision_id = plan.get("approved_revision_id")
    for revision in plan.get("revisions", []):
        if isinstance(revision, dict) and revision.get("revision_id") == approved_revision_id:
            return revision
    return None


def build_context_task_prompt(context: dict, task: dict, plan_revision: dict) -> str:
    """Build the bounded prompt used to execute one approved context-plan task."""
    security_context = context.get("security_context") or build_context_security_context(context)
    return _render_context_prompt_template(
        "context_task_execution",
        {
            "task_summary": "\n".join([
                f"- Task id: {task.get('id')}",
                f"- Task title: {task.get('title')}",
                f"- Task objective: {task.get('objective')}",
            ]),
            "plan_revision_summary": "\n".join([
                f"- Approved revision: {plan_revision.get('revision_id')}",
                f"- Context snapshot hash: {plan_revision.get('context_snapshot_hash')}",
            ]),
            "security_context_summary": _security_context_prompt_summary(security_context),
        },
    )


def execute_context_plan(context_id: str) -> dict:
    """Execute the approved context-intelligence plan and persist task results."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return _context_plan_execution_error(
            "context_not_found",
            "Context not found.",
            status_code=404,
        )

    plan = context.get("context_intelligence_plan")
    if not isinstance(plan, dict) or plan.get("status") != "approved":
        return _context_plan_execution_error(
            "context_plan_not_approved",
            "Approve the context intelligence plan before executing it.",
            status_code=409,
        )
    plan_revision = context_plan_revision(plan)
    if not plan_revision:
        return _context_plan_execution_error(
            "context_plan_revision_not_found",
            "Approved context plan revision not found.",
            status_code=409,
        )

    started_at = datetime.now(timezone.utc).isoformat()
    task_results = {
        "version": CONTEXT_TASK_RESULTS_VERSION,
        "status": "running",
        "plan_revision_id": plan_revision["revision_id"],
        "context_snapshot_hash": plan_revision.get("context_snapshot_hash"),
        "started_at": started_at,
        "updated_at": started_at,
        "completed_at": None,
        "tasks": [],
    }
    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {"$set": {"status": "context_plan_executing", "context_task_results": task_results}},
    )

    completed_tasks = []
    for task in plan_revision.get("tasks", []):
        task_result = _execute_context_plan_task(context, task, plan_revision)
        completed_tasks.append(task_result)
        task_results["tasks"] = completed_tasks
        task_results["updated_at"] = datetime.now(timezone.utc).isoformat()
        mongo.db.contexts.update_one(
            {"_id": context_obj_id},
            {"$set": {"context_task_results": task_results}},
        )
        if task_result["status"] == "failed":
            task_results["status"] = "failed"
            task_results["completed_at"] = datetime.now(timezone.utc).isoformat()
            mongo.db.contexts.update_one(
                {"_id": context_obj_id},
                {"$set": {"status": "context_plan_failed", "context_task_results": task_results}},
            )
            return _context_plan_execution_error(
                task_result["error"]["error_code"],
                task_result["error"]["safe_message"],
                details={"task_id": task_result["task_id"]},
            )

    completed_at = datetime.now(timezone.utc).isoformat()
    task_results["status"] = "completed"
    task_results["updated_at"] = completed_at
    task_results["completed_at"] = completed_at
    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {"$set": {"status": "context_plan_executed", "context_task_results": task_results}},
    )
    return {
        "success": True,
        "stage": "context_plan_execution",
        "context_id": context_id,
        "plan_revision_id": task_results["plan_revision_id"],
        "task_count": len(completed_tasks),
        "context_task_results": task_results,
    }


def _execute_context_plan_task(context: dict, task: dict, plan_revision: dict) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    task_id = str(task.get("id") or "unknown")
    base_result = {
        "task_id": task_id,
        "title": task.get("title"),
        "objective": task.get("objective"),
        "started_at": started_at,
        "completed_at": None,
    }
    try:
        structured_result = run_structured_with_agent(
            build_context_task_prompt(context, task, plan_revision),
            schema_name="context_agent_task_result",
            json_schema=context_phase_output_schema("context_task_result"),
            context_id=str(context["_id"]),
            model_version=context.get("version", "0.1.0"),
        )
        result = _context_task_result_text(structured_result)
        completed_at = datetime.now(timezone.utc).isoformat()
        return {
            **base_result,
            "status": "completed",
            "result": str(result or "").strip(),
            "structured_result": structured_result,
            "completed_at": completed_at,
        }
    except Exception:
        completed_at = datetime.now(timezone.utc).isoformat()
        return {
            **base_result,
            "status": "failed",
            "result": None,
            "completed_at": completed_at,
            "error": {
                "error_type": "dependency_error",
                "error_code": "context_task_execution_failed",
                "safe_message": "Context plan task execution failed.",
                "status_code": 502,
            },
        }


def _context_plan_execution_error(
    error_code: str,
    message: str,
    *,
    status_code: int = 500,
    details: dict | None = None,
) -> dict:
    return {
        "success": False,
        "stage": "context_plan_execution",
        "error_type": "workflow_error",
        "error_code": error_code,
        "message": message,
        "status_code": status_code,
        "details": details or {},
    }


def synthesize_final_context(context_id: str) -> dict:
    """Synthesize completed task results into the canonical final context."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return _final_context_error("context_not_found", "Context not found.", status_code=404)

    task_results = context.get("context_task_results")
    if not isinstance(task_results, dict) or task_results.get("status") != "completed":
        return _final_context_error(
            "context_task_results_not_completed",
            "Execute the approved context plan before final context synthesis.",
            status_code=409,
        )
    plan = context.get("context_intelligence_plan")
    if not isinstance(plan, dict) or plan.get("status") != "approved":
        return _final_context_error(
            "context_plan_not_approved",
            "Approve the context intelligence plan before final context synthesis.",
            status_code=409,
        )
    plan_revision = context_plan_revision(plan)
    if not plan_revision:
        return _final_context_error(
            "context_plan_revision_not_found",
            "Approved context plan revision not found.",
            status_code=409,
        )
    if task_results.get("plan_revision_id") != plan_revision.get("revision_id"):
        return _final_context_error(
            "context_task_results_revision_mismatch",
            "Context task results do not match the active approved plan revision.",
            status_code=409,
        )
    security_context = context.get("security_context")
    if not isinstance(security_context, dict):
        security_context = build_context_security_context(context)
    if security_context.get("analysis", {}).get("missing_information"):
        return _final_context_error(
            "security_context_not_sufficient",
            "Complete the security context before final context synthesis.",
            status_code=409,
        )

    final_context = build_final_context(
        context,
        security_context=security_context,
        plan_revision=plan_revision,
    )
    refined_prompt = render_final_context_prompt(final_context)
    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {
            "$set": {
                "status": "context_ready_for_policy",
                "final_context": final_context,
                "refined_prompt": refined_prompt,
                "security_context": security_context,
                "security_context_version": SECURITY_CONTEXT_VERSION,
            }
        },
    )
    return {
        "success": True,
        "stage": "final_context_synthesis",
        "context_id": context_id,
        "final_context": final_context,
        "refined_prompt": refined_prompt,
    }


def build_final_context(
    context: dict,
    *,
    security_context: dict | None = None,
    plan_revision: dict | None = None,
) -> dict:
    """Build a versioned final-context artifact from completed task results."""
    security_context = security_context or context.get("security_context") or build_context_security_context(context)
    task_results = context.get("context_task_results") or {}
    approved_tasks = [
        {
            "task_id": task.get("id"),
            "order": task.get("order"),
            "title": task.get("title"),
            "objective": task.get("objective"),
        }
        for task in (plan_revision or {}).get("tasks", [])
        if isinstance(task, dict)
    ]
    tasks = [
        _final_context_task_from_result(task)
        for task in task_results.get("tasks", [])
        if isinstance(task, dict)
    ]
    task_items = [
        {
            "item_id": task.get("task_id") or f"task-{index + 1}",
            "order": index + 1,
            "title": task.get("title") or f"Context task {index + 1}",
            "status": task.get("status") or "unknown",
            "content": task.get("result") or "",
            "findings": task.get("findings", []),
            "assumptions": task.get("assumptions", []),
            "missing_details": task.get("missing_details", []),
            "risks": task.get("risks", []),
            "policy_implications": task.get("policy_implications", []),
            "rag_retrieval_hints": task.get("rag_retrieval_hints", {}),
        }
        for index, task in enumerate(tasks)
        if task.get("result")
    ]
    synthesized_at = datetime.now(timezone.utc).isoformat()
    return {
        "version": FINAL_CONTEXT_VERSION,
        "status": "ready",
        "context_ready_for_policy": True,
        "synthesized_at": synthesized_at,
        "plan_revision_id": task_results.get("plan_revision_id"),
        "context_snapshot_hash": task_results.get("context_snapshot_hash"),
        "approved_tasks": approved_tasks,
        "sections": {
            "company_profile": {
                "status": "accepted",
                "content": _final_context_company_profile(security_context),
            },
            "security_scope": {
                "status": "accepted",
                "content": _final_context_security_scope(security_context),
            },
            "task_findings": {
                "status": "accepted",
                "content": "\n\n".join(
                    f"{task['title']}:\n{task['result']}"
                    for task in tasks
                    if task.get("result")
                ),
                "items": task_items,
            },
            "assumptions_and_missing_information": {
                "status": "accepted",
                "content": _final_context_assumptions(security_context),
            },
        },
    }


def _final_context_task_from_result(task: dict) -> dict:
    """Normalize persisted task results for final-context synthesis."""
    structured_result = task.get("structured_result")
    if isinstance(structured_result, dict):
        rendered_result = _context_task_result_text(structured_result)
        return {
            "task_id": task.get("task_id"),
            "title": task.get("title"),
            "status": task.get("status"),
            "result": rendered_result or str(task.get("result") or "").strip(),
            "findings": _string_list(structured_result.get("findings")),
            "assumptions": _string_list(structured_result.get("assumptions")),
            "missing_details": _string_list(structured_result.get("missing_details")),
            "risks": _string_list(structured_result.get("risks")),
            "policy_implications": _string_list(structured_result.get("policy_implications")),
            "rag_retrieval_hints": (
                structured_result.get("rag_retrieval_hints")
                if isinstance(structured_result.get("rag_retrieval_hints"), dict)
                else {}
            ),
        }

    return {
        "task_id": task.get("task_id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "result": str(task.get("result") or "").strip(),
        "findings": [],
        "assumptions": [],
        "missing_details": [],
        "risks": [],
        "policy_implications": [],
        "rag_retrieval_hints": {},
    }


def _string_list(values) -> list[str]:
    """Return only non-empty string values from provider payload fields."""
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def render_final_context_prompt(final_context: dict) -> str:
    """Render the canonical prompt consumed by Policy Agent."""
    sections = final_context.get("sections", {})
    section_lines = []
    for title, section in sections.items():
        section_lines.extend([
            title.replace("_", " ").title(),
            str(section.get("content") or "").strip(),
            "",
        ])
    return _render_context_prompt_template(
        "policy_handoff",
        {
            "final_context_metadata": "\n".join([
                f"- Final context version: {final_context.get('version')}",
                f"- Plan revision: {final_context.get('plan_revision_id') or 'unknown'}",
                f"- Context snapshot hash: {final_context.get('context_snapshot_hash') or 'unknown'}",
            ]),
            "final_context_sections": "\n".join(section_lines).strip(),
        },
    )


def mark_final_context_sections_for_improvement(context_id: str, comments_by_section: dict) -> dict:
    """Mark final-context sections as needing user-requested improvement."""
    if not isinstance(comments_by_section, dict):
        comments_by_section = {}
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return _final_context_error("context_not_found", "Context not found.", status_code=404)

    final_context = context.get("final_context")
    sections = final_context.get("sections") if isinstance(final_context, dict) else None
    if not isinstance(sections, dict):
        return _final_context_error(
            "final_context_not_ready",
            "Synthesize the final context before marking improvements.",
            status_code=409,
        )

    marked_sections = []
    now = datetime.now(timezone.utc).isoformat()
    for section_id, comment in (comments_by_section or {}).items():
        comment_text = str(comment or "").strip()
        if not comment_text or section_id not in sections:
            continue
        section = dict(sections[section_id])
        section["status"] = "needs_improvement"
        section.setdefault("comments", [])
        section["comments"].append({
            "comment": comment_text,
            "created_at": now,
            "source": "user_review",
        })
        sections[section_id] = section
        marked_sections.append(section_id)

    if not marked_sections:
        return _final_context_error(
            "final_context_section_comment_required",
            "Select a final-context section and provide an improvement comment.",
            status_code=400,
        )

    updated_final_context = {
        **final_context,
        "status": "needs_improvement",
        "context_ready_for_policy": False,
        "sections": sections,
        "updated_at": now,
    }
    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {
            "$set": {
                "status": "final_context_needs_improvement",
                "final_context": updated_final_context,
            }
        },
    )
    return {
        "success": True,
        "stage": "final_context_section_review",
        "context_id": context_id,
        "marked_sections": marked_sections,
        "final_context": updated_final_context,
    }


def regenerate_final_context_sections(context_id: str) -> dict:
    """Regenerate sections marked for improvement and create lesson candidates."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return _final_context_error("context_not_found", "Context not found.", status_code=404)

    final_context = context.get("final_context")
    sections = final_context.get("sections") if isinstance(final_context, dict) else None
    if not isinstance(sections, dict):
        return _final_context_error(
            "final_context_not_ready",
            "Synthesize the final context before regenerating sections.",
            status_code=409,
        )

    now = datetime.now(timezone.utc).isoformat()
    regenerated_sections = []
    lesson_candidates = []
    existing_lessons = list(context.get("context_lessons") or [])
    for section_id, section in list(sections.items()):
        if not isinstance(section, dict) or section.get("status") != "needs_improvement":
            continue
        comments = [
            str(item.get("comment") or "").strip()
            for item in section.get("comments", [])
            if isinstance(item, dict) and str(item.get("comment") or "").strip()
        ]
        comment_summary = " ".join(comments)
        regenerated_content = _regenerate_final_context_section_content(
            section_id,
            section,
            context,
            comment_summary,
        )
        updated_section = {
            **section,
            "status": "accepted",
            "content": regenerated_content,
            "regenerated_at": now,
            "regeneration_source": "user_review",
        }
        sections[section_id] = updated_section
        regenerated_sections.append(section_id)
        lesson_candidates.append(
            _build_context_lesson_candidate(
                context,
                section_id,
                comment_summary,
                regenerated_content,
                len(existing_lessons) + len(lesson_candidates) + 1,
                now,
            )
        )

    if not regenerated_sections:
        return _final_context_error(
            "final_context_sections_not_marked",
            "No final-context sections are marked for improvement.",
            status_code=409,
        )

    updated_final_context = {
        **final_context,
        "status": "ready",
        "context_ready_for_policy": True,
        "sections": sections,
        "updated_at": now,
    }
    refined_prompt = render_final_context_prompt(updated_final_context)
    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {
            "$set": {
                "status": "context_ready_for_policy",
                "final_context": updated_final_context,
                "refined_prompt": refined_prompt,
                "context_lessons": existing_lessons + lesson_candidates,
            }
        },
    )
    return {
        "success": True,
        "stage": "final_context_section_regeneration",
        "context_id": context_id,
        "regenerated_sections": regenerated_sections,
        "lesson_candidates": lesson_candidates,
        "final_context": updated_final_context,
        "refined_prompt": refined_prompt,
    }


def export_context_lessons(context_id: str) -> dict:
    """Return reviewed context lessons ready for explicit RAG ingestion."""
    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return _final_context_error("context_not_found", "Context not found.", status_code=404)

    lessons = [
        lesson
        for lesson in context.get("context_lessons", [])
        if isinstance(lesson, dict) and lesson.get("status") == "approved_for_export"
    ]
    return {
        "success": True,
        "stage": "context_lessons_export",
        "context_id": context_id,
        "lessons": lessons,
        "count": len(lessons),
    }


def update_context_lesson_status(context_id: str, lesson_id: str, status: str) -> dict:
    """Update the review/export status for one embedded context lesson."""
    if status not in {"pending_review", "approved_for_export"}:
        return _final_context_error(
            "context_lesson_status_invalid",
            "Context lesson status is invalid.",
            status_code=400,
        )

    context_obj_id = ObjectId(context_id)
    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        return _final_context_error("context_not_found", "Context not found.", status_code=404)

    lessons = []
    updated_lesson = None
    now = datetime.now(timezone.utc).isoformat()
    for lesson in context.get("context_lessons", []):
        if not isinstance(lesson, dict):
            continue
        candidate = dict(lesson)
        if candidate.get("lesson_id") == lesson_id:
            candidate["status"] = status
            candidate["reviewed_at"] = now
            updated_lesson = candidate
        lessons.append(candidate)

    if not updated_lesson:
        return _final_context_error(
            "context_lesson_not_found",
            "Context lesson not found.",
            status_code=404,
        )

    mongo.db.contexts.update_one(
        {"_id": context_obj_id},
        {"$set": {"context_lessons": lessons}},
    )
    return {
        "success": True,
        "stage": "context_lesson_review",
        "context_id": context_id,
        "lesson": updated_lesson,
    }


def _regenerate_final_context_section_content(
    section_id: str,
    section: dict,
    context: dict,
    comment_summary: str,
) -> str:
    base_content = str(section.get("content") or "").strip()
    plan = context.get("context_intelligence_plan") or {}
    plan_revision = context_plan_revision(plan) or {}
    task_titles = [
        str(task.get("title") or "").strip()
        for task in plan_revision.get("tasks", [])
        if isinstance(task, dict) and task.get("title")
    ]
    lines = [base_content] if base_content else [section_id.replace("_", " ").title()]
    if comment_summary:
        lines.append(f"User review addressed: {comment_summary}")
    if task_titles:
        lines.append(f"Approved planning basis: {', '.join(task_titles)}.")
    return "\n\n".join(lines).strip()


def _build_context_lesson_candidate(
    context: dict,
    section_id: str,
    comment_summary: str,
    regenerated_content: str,
    sequence: int,
    created_at: str,
) -> dict:
    security_context = context.get("security_context") or build_context_security_context(context)
    profile = security_context.get("profile", {})
    return {
        "lesson_id": f"lesson-{sequence}",
        "status": "pending_review",
        "source": "final_context_section_improvement",
        "section_id": section_id,
        "created_at": created_at,
        "statement": (
            f"Review feedback for {section_id.replace('_', ' ')} should be considered "
            f"when building similar company security contexts."
        ),
        "review_comment": comment_summary,
        "applicability": {
            "sector": profile.get("sector"),
            "countries": profile.get("operating_countries", []),
            "plan_revision_id": (context.get("final_context") or {}).get("plan_revision_id"),
            "final_context_version": (context.get("final_context") or {}).get("version"),
        },
        "evidence": {
            "section_content": regenerated_content,
        },
    }


def _final_context_company_profile(security_context: dict) -> str:
    profile = security_context["profile"]
    return (
        f"Sector: {profile['sector'] or 'unknown'}. "
        f"Activity: {profile['activity'] or 'unknown'}. "
        f"Countries: {_format_list(profile['operating_countries'])}. "
        f"Region: {profile['region'] or 'unknown'}."
    )


def _final_context_security_scope(security_context: dict) -> str:
    assets = security_context["information_assets"]
    posture = security_context["security_posture"]
    intent = security_context["policy_intent"]
    compliance = security_context["compliance"]
    return (
        f"Critical assets: {_format_list(assets['critical_assets'])}. "
        f"Data categories: {_format_list(assets['data_categories'])}. "
        f"Third-party dependencies: {_format_list(assets['third_party_dependencies'])}. "
        f"Known gaps: {_format_list(posture['known_gaps'])}. "
        f"Regulatory hints: {_format_list(compliance['regulatory_hints'])}. "
        f"Policy objective: {intent['need'] or 'unknown'}."
    )


def _final_context_assumptions(security_context: dict) -> str:
    missing = security_context.get("analysis", {}).get("missing_information", [])
    confidence = security_context.get("analysis", {}).get("confidence", "unknown")
    if missing:
        return f"Confidence: {confidence}. Missing information: {_format_list(missing)}."
    return f"Confidence: {confidence}. No required context-building gaps remain."


def _final_context_error(error_code: str, message: str, *, status_code: int) -> dict:
    return {
        "success": False,
        "stage": "final_context_synthesis",
        "error_type": "workflow_error",
        "error_code": error_code,
        "message": message,
        "status_code": status_code,
    }


def _context_snapshot_hash(context_snapshot: dict) -> str:
    """Return a deterministic hash for approval-time context snapshots."""
    serialized = json.dumps(
        context_snapshot or {},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "unknown"


def build_context_security_context(context_data: dict, *, additional_need: str | None = None) -> dict:
    """Build the persisted security_context from Context Agent-owned fields."""
    answers = {
        field: str(context_data.get(field, "") or "").strip()
        for field in CONTEXT_ANSWER_FIELDS
    }
    if additional_need and additional_need.strip():
        current_need = answers.get("need", "")
        answers["need"] = "\n".join(
            part for part in (current_need, additional_need.strip()) if part
        )
    return build_security_context_from_answers(
        answers,
        language=str(context_data.get("language", "en") or "en"),
    )


def public_security_context_payload(context_id: str, context: dict) -> dict:
    """Return a bounded public payload for a context's structured security context."""
    security_context = context.get("security_context")
    if not isinstance(security_context, dict):
        security_context = build_context_security_context(context)
    return {
        "success": True,
        "context_id": context_id,
        "security_context_version": context.get(
            "security_context_version",
            SECURITY_CONTEXT_VERSION,
        ),
        "security_context": security_context,
    }


def business_context_from_context_record(context: dict) -> dict:
    """Return the downstream shallow business_context for Policy Agent."""
    security_context = context.get("security_context")
    if not isinstance(security_context, dict):
        security_context = build_context_security_context(context)
    return security_context_to_business_context(security_context)


def run_with_agent(prompt: str, context_id: str = None, model_version: str = None) -> str:
    """
    Execute the configured agent using the initial prompt.
    The context_id can be used for session naming, assistant_id, or traceability.
    """
    _ = model_version
    agent = create_agent_from_config(_agent_config_path())
    agent.create(context_id=context_id)  # pass context_id when persistence is needed
    return agent.run(prompt, context_id)


def run_structured_with_agent(
    prompt: str,
    *,
    schema_name: str,
    json_schema: dict,
    context_id: str = None,
    model_version: str = None,
) -> dict:
    """Execute the configured agent using a structured schema when supported."""
    _ = model_version
    agent = create_agent_from_config(_agent_config_path())
    if hasattr(agent, "run_structured"):
        return agent.run_structured(
            prompt,
            schema_name=schema_name,
            json_schema=json_schema,
            context_id=context_id,
        )

    agent.create(context_id=context_id)
    raw_text = agent.run(prompt, context_id)
    return {
        "task_id": "unknown",
        "status": "completed",
        "findings": [str(raw_text or "").strip()],
        "assumptions": [],
        "missing_details": [],
        "risks": [],
        "policy_implications": [],
        "rag_retrieval_hints": {
            "collection_families": [],
            "jurisdictions": [],
            "sectors": [],
            "methodologies": [],
            "query_terms": [],
        },
        "raw_text": str(raw_text or "").strip(),
    }


def _context_task_result_text(structured_result: dict) -> str:
    """Render a structured context task result into current UI text."""
    if not isinstance(structured_result, dict):
        return ""
    if structured_result.get("raw_text"):
        return str(structured_result["raw_text"]).strip()

    sections = [
        ("Findings", structured_result.get("findings")),
        ("Assumptions", structured_result.get("assumptions")),
        ("Missing details", structured_result.get("missing_details")),
        ("Risks", structured_result.get("risks")),
        ("Policy implications", structured_result.get("policy_implications")),
    ]
    lines = []
    for title, values in sections:
        if not values:
            continue
        lines.append(f"{title}:")
        lines.extend(f"- {value}" for value in values if str(value).strip())
    hints = structured_result.get("rag_retrieval_hints") or {}
    query_terms = hints.get("query_terms") if isinstance(hints, dict) else []
    if query_terms:
        lines.append("RAG retrieval hints:")
        lines.extend(f"- {term}" for term in query_terms if str(term).strip())
    return "\n".join(lines).strip()


def _result_error(error: str, details: str = "", status_code: int = 500) -> dict:
    return {"success": False, "error": error, "details": details, "status_code": status_code}


def _pipeline_success(*, stage: str, **payload) -> dict:
    result = {"success": True, "stage": stage}
    result.update(payload)
    return result


def _pipeline_error(exc: PipelineStepError) -> dict:
    payload = {
        "success": False,
        "stage": exc.stage,
        "error_type": exc.error_type,
        "error_code": exc.error_code,
        "message": exc.message,
        "details": exc.details,
        "status_code": exc.status_code,
    }
    correlation_id = exc.correlation_id or _get_correlation_id()
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload


def _get_correlation_id(payload: dict | None = None, context_id: str | None = None) -> str | None:
    """Resolve correlation id from the request boundary or current payload/context."""
    request_correlation_id = get_request_correlation_id()
    if request_correlation_id:
        return request_correlation_id
    if isinstance(payload, dict) and payload.get("correlation_id"):
        return str(payload["correlation_id"])
    if isinstance(payload, dict) and payload.get("context_id"):
        return str(payload["context_id"])
    if context_id:
        return str(context_id)
    return None


def _dependency_headers(correlation_id: str | None) -> dict:
    """Build outbound service headers with correlation metadata when available."""
    if not correlation_id:
        return {}
    return {"X-Correlation-ID": correlation_id}


def _dependency_timeout(config_name: str, default: float = 30.0) -> float:
    """Read outbound dependency timeout from app config."""
    timeout_value = current_app.config.get(config_name, default)
    try:
        timeout_seconds = float(timeout_value)
    except (TypeError, ValueError):
        return default
    return timeout_seconds if timeout_seconds > 0 else default


def _dependency_error_details(
    *,
    response: requests.Response | None,
    target_service: str,
    operation: str,
) -> dict:
    """Extract stable dependency error details without leaking raw response bodies."""
    details = {
        "target_service": target_service,
        "operation": operation,
    }
    if response is None:
        return details

    details["dependency_status_code"] = response.status_code
    try:
        body = response.json()
    except ValueError:
        return details

    if isinstance(body, dict):
        if body.get("error_type"):
            details["dependency_error_type"] = body["error_type"]
        if body.get("error_code"):
            details["dependency_error_code"] = body["error_code"]
        if body.get("correlation_id"):
            details["dependency_correlation_id"] = body["correlation_id"]
    return details


def _pipeline_diagnostics_collection():
    """Return the collection used for bounded pipeline diagnostics."""
    return mongo.db.pipeline_diagnostics


def _upsert_pipeline_diagnostic(
    *,
    correlation_id: str | None,
    context_id: str | None,
    hop: dict,
    status: str | None = None,
    last_error: dict | None = None,
    completed: bool = False,
) -> None:
    """Persist a bounded cross-service diagnostic view keyed by correlation id."""
    if not correlation_id:
        return

    now = datetime.now(timezone.utc)
    update_doc = {
        "$setOnInsert": {
            "correlation_id": correlation_id,
            "created_at": now,
            "ownership": {
                "owner_service": "context-agent",
                "source_of_truth": False,
                "collection": "pipeline_diagnostics",
                "view_type": "pipeline_diagnostic",
            },
        },
        "$set": {
            "context_id": context_id,
            "updated_at": now,
        },
        "$push": {"hops": {"$each": [hop], "$slice": -MAX_PIPELINE_DIAGNOSTIC_HOPS}},
    }
    if status is not None:
        update_doc["$set"]["status"] = status
    if last_error is not None:
        update_doc["$set"]["last_error"] = last_error
    if completed:
        update_doc["$set"]["completed_at"] = now

    try:
        _pipeline_diagnostics_collection().update_one(
            {"correlation_id": correlation_id},
            update_doc,
            upsert=True,
        )
    except Exception:
        logger.warning(
            build_log_event(
                event="context.pipeline_diagnostic.persistence_failed",
                stage="diagnostics",
                context_id=context_id,
                correlation_id=correlation_id,
            ),
            exc_info=True,
        )


def get_pipeline_diagnostic(correlation_id: str) -> dict | None:
    """Return a persisted pipeline diagnostic document by correlation id."""
    diagnostic = _pipeline_diagnostics_collection().find_one({"correlation_id": correlation_id})
    if not diagnostic:
        return None
    if "_id" in diagnostic:
        diagnostic["_id"] = str(diagnostic["_id"])
    for field in ("created_at", "updated_at", "completed_at"):
        if field in diagnostic and hasattr(diagnostic[field], "isoformat"):
            diagnostic[field] = diagnostic[field].isoformat()
    for hop in diagnostic.get("hops", []):
        for field in ("started_at", "completed_at"):
            if field in hop and hasattr(hop[field], "isoformat"):
                hop[field] = hop[field].isoformat()
    return diagnostic


def get_context_and_prompt(context_id: str) -> dict:
    """Fetch context data and the refined prompt required by policy-agent."""
    correlation_id = _get_correlation_id(context_id=context_id)
    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise PipelineStepError(
            stage="context_fetch",
            message="Invalid context_id format.",
            error_type="contract_error",
            error_code="invalid_context_id",
            status_code=400,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        ) from exc

    context = mongo.db.contexts.find_one({"_id": context_obj_id})
    if not context:
        raise PipelineStepError(
            stage="context_fetch",
            message="Context not found.",
            error_type="validation_error",
            error_code="context_not_found",
            status_code=404,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        )

    if context.get("status") != "context_ready_for_policy":
        raise PipelineStepError(
            stage="context_fetch",
            message="Context is not ready for policy generation.",
            error_type="validation_error",
            error_code="context_not_ready_for_policy",
            status_code=409,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        )

    refined_prompt = (context.get("refined_prompt") or "").strip()
    if not refined_prompt:
        prompt_entry = mongo.db.interactions.find_one(
            {"context_id": context_obj_id, "question_id": "refined_prompt"}
        )
        if not prompt_entry:
            if "refined_prompt" in context:
                raise PipelineStepError(
                    stage="context_fetch",
                    message="Refined prompt is empty.",
                    error_type="validation_error",
                    error_code="empty_refined_prompt",
                    status_code=400,
                    details={"context_id": context_id},
                    correlation_id=correlation_id,
                )
            raise PipelineStepError(
                stage="context_fetch",
                message="Refined prompt not found.",
                error_type="validation_error",
                error_code="refined_prompt_not_found",
                status_code=404,
                details={"context_id": context_id},
                correlation_id=correlation_id,
            )

        refined_prompt = prompt_entry.get("answer", "").strip()
        if not refined_prompt:
            raise PipelineStepError(
                stage="context_fetch",
                message="Refined prompt is empty.",
                error_type="validation_error",
                error_code="empty_refined_prompt",
                status_code=400,
                details={"context_id": context_id},
                correlation_id=correlation_id,
            )

    return {
        "context_id": context_id,
        "refined_prompt": refined_prompt,
        "language": context.get("language", "en"),
        "model_version": str(context.get("version", "0.1.0")),
        "business_context": business_context_from_context_record(context),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }


def call_policy_agent(context_payload: dict) -> dict:
    """Call policy-agent and return parsed JSON response."""
    policy_agent_url = current_app.config.get("POLICY_AGENT_URL", "http://policy-agent:5000")
    correlation_id = _get_correlation_id(context_payload)
    timeout_seconds = _dependency_timeout("POLICY_AGENT_TIMEOUT_SECONDS")
    started_at = datetime.now(timezone.utc)
    started_perf = perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="context.policy.request",
        stage="policy_generation",
        context_id=context_payload.get("context_id"),
        correlation_id=correlation_id,
        target_service="policy-agent",
        operation="generate_policy",
        timeout_seconds=timeout_seconds,
    )
    try:
        response = requests.post(
            f"{policy_agent_url}/generate_policy",
            json=context_payload,
            headers=_dependency_headers(correlation_id),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        completed_at = datetime.now(timezone.utc)
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=context_payload.get("context_id"),
            status="in_progress",
            hop={
                "service": "context-agent",
                "stage": "policy_generation",
                "operation": "generate_policy",
                "target_service": "policy-agent",
                "outcome": "success",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code,
            },
        )
        log_event(
            logger,
            logging.INFO,
            event="context.policy.response",
            stage="policy_generation",
            context_id=context_payload.get("context_id"),
            correlation_id=correlation_id,
            target_service="policy-agent",
            operation="generate_policy",
            status_code=response.status_code,
            result="success",
        )
        return response.json()
    except requests.exceptions.RequestException as exc:
        response = exc.response if isinstance(exc, requests.exceptions.HTTPError) else None
        completed_at = datetime.now(timezone.utc)
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=context_payload.get("context_id"),
            status="failed",
            last_error={
                "stage": "policy_generation",
                "error_type": "dependency_error",
                "error_code": "policy_agent_request_failed",
            },
            hop={
                "service": "context-agent",
                "stage": "policy_generation",
                "operation": "generate_policy",
                "target_service": "policy-agent",
                "outcome": "failure",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code if response is not None else None,
                "error_type": "dependency_error",
                "error_code": "policy_agent_request_failed",
            },
        )
        logger.warning(
            build_log_event(
                event="context.policy.response",
                stage="policy_generation",
                context_id=context_payload.get("context_id"),
                correlation_id=correlation_id,
                target_service="policy-agent",
                operation="generate_policy",
                status_code=response.status_code if response is not None else None,
                result="failure",
            ),
            exc_info=exc,
        )
        raise PipelineStepError(
            stage="policy_generation",
            message="Policy generation failed.",
            error_type="dependency_error",
            error_code="policy_agent_request_failed",
            status_code=502,
            details=_dependency_error_details(
                response=response,
                target_service="policy-agent",
                operation="generate_policy",
            ),
            correlation_id=correlation_id,
        ) from exc


def trigger_policy_generation(context_id: str) -> dict:
    """Generate policy data from stored context and refined prompt."""
    log_event(
        logger,
        logging.INFO,
        event="context.pipeline.policy_generation_started",
        stage="policy_generation",
        context_id=context_id,
        correlation_id=_get_correlation_id(context_id=context_id),
    )
    try:
        payload = get_context_and_prompt(context_id)
        policy_data = call_policy_agent(payload)
        log_event(
            logger,
            logging.INFO,
            event="context.pipeline.policy_generation_completed",
            stage="policy_generation",
            context_id=context_id,
            correlation_id=_get_correlation_id(payload, context_id),
            result="success",
        )
        return _pipeline_success(stage="policy_generation", policy_data=policy_data)
    except PipelineStepError as exc:
        return _pipeline_error(exc)
    except Exception as exc:  # unexpected errors
        logger.exception("Unexpected policy generation failure for context_id=%s", context_id)
        return _pipeline_error(
            PipelineStepError(
                stage="policy_generation",
                message="Policy generation failed.",
                error_type="internal_error",
                error_code="policy_generation_unexpected_failure",
                status_code=500,
                details={"operation": "trigger_policy_generation"},
                correlation_id=_get_correlation_id(context_id=context_id),
            )
        )


def call_validator_agent(policy_data: dict) -> dict:
    """Call validator-agent and return parsed JSON response."""
    validator_agent_url = current_app.config.get("VALIDATOR_AGENT_URL", "http://validator-agent:5000")
    correlation_id = _get_correlation_id(policy_data)
    timeout_seconds = _dependency_timeout("VALIDATOR_AGENT_TIMEOUT_SECONDS")
    started_at = datetime.now(timezone.utc)
    started_perf = perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="context.validator.request",
        stage="validation",
        context_id=policy_data.get("context_id"),
        correlation_id=correlation_id,
        target_service="validator-agent",
        operation="validate_policy",
        timeout_seconds=timeout_seconds,
    )
    try:
        response = requests.post(
            f"{validator_agent_url}/validate-policy",
            json=policy_data,
            headers=_dependency_headers(correlation_id),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        completed_at = datetime.now(timezone.utc)
        response_body = response.json()
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=policy_data.get("context_id"),
            status="in_progress",
            hop={
                "service": "context-agent",
                "stage": "validation",
                "operation": "validate_policy",
                "target_service": "validator-agent",
                "outcome": "success",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code,
                "validation_status": response_body.get("status") if isinstance(response_body, dict) else None,
            },
        )
        log_event(
            logger,
            logging.INFO,
            event="context.validator.response",
            stage="validation",
            context_id=policy_data.get("context_id"),
            correlation_id=correlation_id,
            target_service="validator-agent",
            operation="validate_policy",
            status_code=response.status_code,
            result="success",
        )
        return response_body
    except requests.exceptions.RequestException as exc:
        response = exc.response if isinstance(exc, requests.exceptions.HTTPError) else None
        completed_at = datetime.now(timezone.utc)
        _upsert_pipeline_diagnostic(
            correlation_id=correlation_id,
            context_id=policy_data.get("context_id"),
            status="failed",
            last_error={
                "stage": "validation",
                "error_type": "dependency_error",
                "error_code": "validator_agent_request_failed",
            },
            hop={
                "service": "context-agent",
                "stage": "validation",
                "operation": "validate_policy",
                "target_service": "validator-agent",
                "outcome": "failure",
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "status_code": response.status_code if response is not None else None,
                "error_type": "dependency_error",
                "error_code": "validator_agent_request_failed",
            },
        )
        logger.warning(
            build_log_event(
                event="context.validator.response",
                stage="validation",
                context_id=policy_data.get("context_id"),
                correlation_id=correlation_id,
                target_service="validator-agent",
                operation="validate_policy",
                status_code=response.status_code if response is not None else None,
                result="failure",
            ),
            exc_info=exc,
        )
        raise PipelineStepError(
            stage="validation",
            message="Policy validation failed.",
            error_type="dependency_error",
            error_code="validator_agent_request_failed",
            status_code=502,
            details=_dependency_error_details(
                response=response,
                target_service="validator-agent",
                operation="validate_policy",
            ),
            correlation_id=correlation_id,
        ) from exc


def store_validated_policy(context_id: str, validated_data: dict) -> dict:
    """Persist a validated policy payload in context interactions."""
    data = validated_data or {}
    correlation_id = _get_correlation_id(data, context_id)
    required_fields = ["policy_text", "generated_at", "policy_agent_version", "language"]
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise PipelineStepError(
            stage="persistence",
            message="Validated policy payload is incomplete.",
            error_type="contract_error",
            error_code="validated_policy_missing_fields",
            status_code=400,
            details={"missing_fields": missing, "context_id": context_id},
            correlation_id=correlation_id,
        )

    try:
        context_obj_id = ObjectId(context_id)
    except Exception as exc:
        raise PipelineStepError(
            stage="persistence",
            message="Invalid context_id format.",
            error_type="contract_error",
            error_code="invalid_context_id",
            status_code=400,
            details={"context_id": context_id},
            correlation_id=correlation_id,
        ) from exc

    validated_at = datetime.now(timezone.utc)
    mongo.db.interactions.insert_one({
        "context_id": context_obj_id,
        "correlation_id": correlation_id,
        "question_id": "validated_policy",
        "question_text": "Agent-generated policy",
        "answer": data["policy_text"],
        "timestamp": validated_at,
        "origin": "agent",
        "status": data.get("status", "review"),
        "recommendations": data.get("recommendations", []),
        "generated_at": data["generated_at"],
        "policy_agent_version": data["policy_agent_version"],
        "language": data["language"],
        "ownership": {
            "owner_service": "context-agent",
            "source_of_truth": False,
            "view_type": "derived_policy_snapshot",
        },
        "policy_ref": {
            "owner_service": "policy-agent",
            "source_collection": "policies",
            "context_id": context_id,
        },
        "validation_ref": {
            "owner_service": "validator-agent",
            "source_collection": "validations",
            "context_id": context_id,
        },
    })
    _upsert_pipeline_diagnostic(
        correlation_id=correlation_id,
        context_id=context_id,
        status="in_progress",
        hop={
            "service": "context-agent",
            "stage": "persistence",
            "operation": "store_validated_policy",
            "outcome": "success",
            "started_at": validated_at,
            "completed_at": validated_at,
            "duration_ms": 0.0,
        },
    )
    log_event(
        logger,
        logging.INFO,
        event="context.pipeline.persistence_completed",
        stage="persistence",
        context_id=context_id,
        correlation_id=correlation_id,
        result="success",
    )
    return _pipeline_success(
        stage="persistence",
        context_id=context_id,
        stored_at=validated_at.isoformat(),
    )


def generate_full_policy_pipeline(context_id: str) -> dict:
    """Execute policy generation, validation, and context persistence pipeline."""
    correlation_id = _get_correlation_id(context_id=context_id)
    started_at = datetime.now(timezone.utc)
    started_perf = perf_counter()
    _upsert_pipeline_diagnostic(
        correlation_id=correlation_id,
        context_id=context_id,
        status="in_progress",
        hop={
            "service": "context-agent",
            "stage": "pipeline",
            "operation": "generate_full_policy_pipeline",
            "outcome": "started",
            "started_at": started_at,
        },
    )
    log_event(
        logger,
        logging.INFO,
        event="context.pipeline.started",
        stage="pipeline",
        context_id=context_id,
        correlation_id=correlation_id,
    )
    try:
        policy_result = trigger_policy_generation(context_id)
        if not policy_result.get("success"):
            _upsert_pipeline_diagnostic(
                correlation_id=policy_result.get("correlation_id", correlation_id),
                context_id=context_id,
                status="failed",
                last_error={
                    "stage": policy_result.get("stage", "policy_generation"),
                    "error_type": policy_result.get("error_type"),
                    "error_code": policy_result.get("error_code"),
                },
                completed=True,
                hop={
                    "service": "context-agent",
                    "stage": policy_result.get("stage", "policy_generation"),
                    "operation": "generate_full_policy_pipeline",
                    "outcome": "failure",
                    "completed_at": datetime.now(timezone.utc),
                    "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                    "error_type": policy_result.get("error_type"),
                    "error_code": policy_result.get("error_code"),
                },
            )
            return policy_result

        policy_data = policy_result["policy_data"]
        validated_data = call_validator_agent(policy_data)
        persistence_result = store_validated_policy(context_id, validated_data)
        _upsert_pipeline_diagnostic(
            correlation_id=_get_correlation_id(validated_data, context_id),
            context_id=context_id,
            status="completed",
            completed=True,
            hop={
                "service": "context-agent",
                "stage": "pipeline",
                "operation": "generate_full_policy_pipeline",
                "outcome": "success",
                "completed_at": datetime.now(timezone.utc),
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "validation_status": validated_data.get("status"),
            },
        )
        log_event(
            logger,
            logging.INFO,
            event="context.pipeline.completed",
            stage="pipeline",
            context_id=context_id,
            correlation_id=_get_correlation_id(validated_data, context_id),
            result="success",
            validation_status=validated_data.get("status"),
            duration_ms=round((perf_counter() - started_perf) * 1000, 3),
        )
        return _pipeline_success(
            stage="completed",
            validated_data=validated_data,
            persistence=persistence_result,
        )
    except PipelineStepError as exc:
        _upsert_pipeline_diagnostic(
            correlation_id=exc.correlation_id or correlation_id,
            context_id=context_id,
            status="failed",
            last_error={
                "stage": exc.stage,
                "error_type": exc.error_type,
                "error_code": exc.error_code,
            },
            completed=True,
            hop={
                "service": "context-agent",
                "stage": exc.stage,
                "operation": "generate_full_policy_pipeline",
                "outcome": "failure",
                "completed_at": datetime.now(timezone.utc),
                "duration_ms": round((perf_counter() - started_perf) * 1000, 3),
                "error_type": exc.error_type,
                "error_code": exc.error_code,
            },
        )
        log_event(
            logger,
            logging.WARNING,
            event="context.pipeline.completed",
            stage=exc.stage,
            context_id=context_id,
            correlation_id=exc.correlation_id or _get_correlation_id(context_id=context_id),
            result="failure",
            error_code=exc.error_code,
            error_type=exc.error_type,
            duration_ms=round((perf_counter() - started_perf) * 1000, 3),
        )
        return _pipeline_error(exc)
    except Exception:
        logger.exception("Unexpected pipeline failure for context_id=%s", context_id)
        return _pipeline_error(
            PipelineStepError(
                stage="pipeline",
                message="Policy pipeline failed.",
                error_type="internal_error",
                error_code="policy_pipeline_unexpected_failure",
                status_code=500,
                details={"context_id": context_id},
                correlation_id=_get_correlation_id(context_id=context_id),
            )
        )


def render_markdown(text):
    """Render markdown text as HTML for context-detail display."""
    return markdown(text or "", extensions=["fenced_code", "tables", "nl2br"])
