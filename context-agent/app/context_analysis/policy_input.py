"""Context-owned, explicit PolicyRequest 1.1 preparation and approval checks."""

from __future__ import annotations

import json
from copy import deepcopy

from app.policy_handoff_contract import validate_policy_handoff_context
from contracts.policy_request_v1 import (
    PolicyRequestError,
    compute_policy_input_hash_v1_1,
    validate_policy_request_v1_1,
)

VERSION = "1.1"
MAX_ANSWERS_BYTES = 32768
_INTENT = {
    "policy_type": "text", "scope": "text", "audience": "strings",
    "exclusions": "exclusions", "requested_instruments": "instruments",
    "document_profile": "profile", "coverage_mode": "coverage", "language": "text",
}
_SCOPE = {
    "legal_entities": "strings", "size_band": "text", "jurisdictions": "strings",
    "sectors": "strings", "services": "strings", "data_categories": "strings",
}
_FACTS = {
    "current_posture": "text", "target_posture": "text", "maturity": "text",
    "risk_appetite": "text", "risk_tolerance": "text", "existing_controls": "strings",
    "known_gaps": "strings", "constraints": "strings", "governance_owner": "text",
    "business_priorities": "strings", "critical_processes": "strings",
}
FIELD_KINDS = {
    **{f"policy_intent.{key}": kind for key, kind in _INTENT.items()},
    **{f"business_facts.entity_scope.{key}": kind for key, kind in _SCOPE.items()},
    **{f"business_facts.{key}": kind for key, kind in _FACTS.items()},
}
MATERIAL_FIELDS = (
    "policy_intent.policy_type", "policy_intent.scope", "policy_intent.audience",
    "policy_intent.exclusions", "policy_intent.document_profile",
    "policy_intent.coverage_mode", "policy_intent.language",
    "business_facts.entity_scope.legal_entities",
    "business_facts.entity_scope.jurisdictions",
    "business_facts.business_priorities", "business_facts.critical_processes",
)
QUESTION_TEXT = {
    "policy_intent.policy_type": "Which security policy domain is requested?",
    "policy_intent.scope": "Which systems, activities and people are in scope?",
    "policy_intent.audience": "Who must use or approve this policy?",
    "policy_intent.exclusions": "Which typed entities, jurisdictions or instruments are excluded? Confirm an empty list if none.",
    "policy_intent.document_profile": "Choose executive, standard or detailed presentation.",
    "policy_intent.coverage_mode": "Choose risk-based, all-applicable or full-instrument coverage.",
    "policy_intent.language": "Which language should the proposal use?",
    "policy_intent.requested_instruments": "Which exact instrument IDs and versions require full coverage?",
    "business_facts.entity_scope.legal_entities": "Which legal entities does the policy cover?",
    "business_facts.entity_scope.jurisdictions": "In which jurisdictions do those entities operate?",
    "business_facts.entity_scope.sectors": "Which sectors are in scope for full instrument coverage?",
    "business_facts.entity_scope.services": "Which services or activities are in scope for full instrument coverage?",
    "business_facts.entity_scope.data_categories": "Which data categories are in scope for full instrument coverage?",
    "business_facts.business_priorities": "Which business priorities should shape the policy?",
    "business_facts.critical_processes": "Which processes are critical to service delivery?",
}
_PROFILES = {"executive", "standard", "detailed"}
_COVERAGE = {"risk_based", "all_applicable", "full_instrument"}
_EXCLUSION_KINDS = {"entity", "jurisdiction", "instrument"}


class PolicyInputError(ValueError):
    """Stable error without reflecting answer content."""

    def __init__(self, code: str, field: str):
        self.code = code
        self.field = field
        super().__init__(f"{code}: {field}")


def _fail(code: str, field: str) -> None:
    raise PolicyInputError(code, field)


def validate_answer_patch(patch: object) -> dict:
    """Accept only typed, explicitly confirmed/qualified Context answers."""
    if not isinstance(patch, dict) or not patch or len(patch) > len(FIELD_KINDS):
        _fail("invalid_answers", "answers")
    if any(not isinstance(key, str) or key not in FIELD_KINDS for key in patch):
        _fail("unknown_answer", "answers")
    try:
        size = len(json.dumps(patch, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise PolicyInputError("invalid_answers", "answers") from exc
    if size > MAX_ANSWERS_BYTES:
        _fail("answers_too_large", "answers")
    clean = {}
    for field, answer in patch.items():
        if answer is None:
            clean[field] = None
            continue
        if not isinstance(answer, dict) or set(answer) != {"value", "confidence"}:
            _fail("invalid_answer", field)
        if not isinstance(answer["confidence"], str) or answer["confidence"] not in {"confirmed", "qualified"}:
            _fail("invalid_confidence", field)
        value = answer["value"]
        kind = FIELD_KINDS[field]
        if kind in {"text", "profile", "coverage"}:
            if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 2000:
                _fail("invalid_value", field)
            if kind == "profile" and value not in _PROFILES:
                _fail("invalid_value", field)
            if kind == "coverage" and value not in _COVERAGE:
                _fail("invalid_value", field)
        elif kind in {"strings", "exclusions"}:
            if not isinstance(value, list) or len(value) > 32 or any(
                not isinstance(item, str) or not item.strip() or item != item.strip() or len(item) > 512
                for item in value
            ) or len(set(value)) != len(value):
                _fail("invalid_value", field)
            if kind == "exclusions" and any(
                ":" not in item or item.split(":", 1)[0] not in _EXCLUSION_KINDS
                or not item.split(":", 1)[1].strip()
                for item in value
            ):
                _fail("untyped_exclusion", field)
        elif kind == "instruments":
            if not isinstance(value, list) or len(value) > 32:
                _fail("invalid_value", field)
            for item in value:
                if (not isinstance(item, dict) or set(item) != {"id", "version"}
                        or any(not isinstance(item[key], str) or not item[key].strip()
                               or item[key] != item[key].strip() or len(item[key]) > 256
                               for key in ("id", "version"))):
                    _fail("invalid_instrument", field)
            if len({item["id"].casefold() for item in value}) != len(value):
                _fail("duplicate_instrument", field)
        clean[field] = deepcopy(answer)
    return clean


def material_questions(answers: dict) -> list[dict]:
    """Ask only fields that change policy scope, coverage or action selection."""
    questions = []
    mode = (answers.get("policy_intent.coverage_mode") or {}).get("value")
    required = list(MATERIAL_FIELDS)
    if mode == "full_instrument":
        required.extend((
            "policy_intent.requested_instruments",
            "business_facts.entity_scope.sectors",
            "business_facts.entity_scope.services",
            "business_facts.entity_scope.data_categories",
        ))
    for field in required:
        answer = answers.get(field)
        value = answer.get("value") if isinstance(answer, dict) else None
        empty = value is None or (isinstance(value, list) and not value and field != "policy_intent.exclusions")
        if empty or answer.get("confidence") != "confirmed":
            questions.append({"field": field, "reason": "material_fact_unconfirmed", "question": QUESTION_TEXT[field]})
    entities = set((answers.get("business_facts.entity_scope.legal_entities") or {}).get("value") or [])
    jurisdictions = set((answers.get("business_facts.entity_scope.jurisdictions") or {}).get("value") or [])
    instruments = {item["id"] for item in ((answers.get("policy_intent.requested_instruments") or {}).get("value") or [])}
    for excluded in (answers.get("policy_intent.exclusions") or {}).get("value") or []:
        kind, name = excluded.split(":", 1)
        targets = {"entity": entities, "jurisdiction": jurisdictions, "instrument": instruments}[kind]
        if name.casefold() in {target.casefold() for target in targets}:
            questions.append({"field": "policy_intent.exclusions", "reason": "contradictory_exclusion",
                              "question": QUESTION_TEXT["policy_intent.exclusions"]})
            break
    return questions


def _decision(answers: dict, field: str, revision: int) -> dict:
    answer = answers.get(field)
    if answer is None:
        return {"value": None, "source": "unknown", "source_ref": None, "confidence": "unknown"}
    return {
        "value": deepcopy(answer["value"]), "source": "provided",
        "source_ref": f"answer:{field}@revision:{revision}",
        "confidence": answer["confidence"],
    }


def _answer_revisions(history: list, answers: dict) -> dict[str, int]:
    """Attribute each answer to its latest actual change, not the snapshot revision."""
    previous = {}
    origins = {}
    for expected_revision, entry in enumerate(history, start=1):
        if (not isinstance(entry, dict) or entry.get("revision") != expected_revision
                or not isinstance(entry.get("answers"), dict)):
            _fail("answer_provenance_missing", "policy_input.revisions")
        snapshot = entry["answers"]
        for field, answer in snapshot.items():
            if previous.get(field) != answer:
                origins[field] = expected_revision
        previous = snapshot
    if previous != answers:
        _fail("answer_provenance_missing", "policy_input.revisions")
    return origins


def _reconcile_handoff_facts(answers: dict, handoff: dict) -> None:
    """Reject exact comparable facts that contradict approved Context answers."""
    business = handoff.get("business_context")
    if not isinstance(business, dict):
        _fail("handoff_facts_missing", "policy_handoff_context.business_context")
    for source_field, answer_field in (
        ("country", "business_facts.entity_scope.jurisdictions"),
        ("sector", "business_facts.entity_scope.sectors"),
    ):
        source = business.get(source_field)
        answer = answers.get(answer_field)
        if source is None or answer is None:
            continue
        if not isinstance(source, str) or not source.strip():
            _fail("handoff_facts_invalid", f"policy_handoff_context.business_context.{source_field}")
        if source.casefold() not in {item.casefold() for item in answer["value"]}:
            _fail("context_fact_conflict", answer_field)
    data_types = business.get("data_types")
    categories = answers.get("business_facts.entity_scope.data_categories")
    if data_types is not None and categories is not None:
        if not isinstance(data_types, list) or any(not isinstance(item, str) for item in data_types):
            _fail("handoff_facts_invalid", "policy_handoff_context.business_context.data_types")
        if not {item.casefold() for item in data_types}.issubset(
            {item.casefold() for item in categories["value"]}
        ):
            _fail("context_fact_conflict", "business_facts.entity_scope.data_categories")


def build_approved_request(context: dict, handoff: dict, *, tenant_id: str) -> dict:
    """Project an exact approved candidate from persisted answers and handoff."""
    state = context.get("policy_input") or {}
    answers = state.get("answers") or {}
    revision = state.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1 or not tenant_id:
        _fail("policy_input_missing", "policy_input")
    history = state.get("revisions") or []
    if (not isinstance(history, list) or not history or not isinstance(history[-1], dict)
            or history[-1].get("revision") != revision
            or history[-1].get("answers") != answers
            or not history[-1].get("recorded_by")):
        _fail("answer_provenance_missing", "policy_input.revisions")
    origins = _answer_revisions(history, answers)
    if context.get("organization_id") != tenant_id:
        _fail("tenant_mismatch", "organization_id")
    plan = context.get("context_intelligence_plan") or {}
    if (plan.get("status") != "approved"
            or plan.get("approved_revision_id") != handoff.get("plan_revision_id")):
        _fail("plan_not_approved", "context_intelligence_plan")
    handoff_result = validate_policy_handoff_context(handoff)
    if not handoff_result["success"]:
        _fail("handoff_not_ready", handoff_result.get("field") or "policy_handoff_context")
    if material_questions(answers):
        _fail("material_questions_open", "policy_input.answers")
    _reconcile_handoff_facts(answers, handoff)
    context_id = str(context["_id"])
    request = {
        "contract": "secpolicy.policy_request", "version": VERSION,
        "context_id": context_id,
        "approved_context": {
            "approval_status": "approved", "context_id": context_id,
            "tenant_id": tenant_id, "plan_revision_id": handoff["plan_revision_id"],
            "snapshot_hash": "0" * 64,
            "legacy_handoff_hash": handoff["context_snapshot_hash"],
            "hash_scope": "policy_input_v1_1",
            "policy_handoff_context": deepcopy(handoff),
        },
        "policy_intent": {
            field: _decision(answers, f"policy_intent.{field}", origins.get(f"policy_intent.{field}", revision))
            for field in _INTENT
        },
        "business_facts": {
            "entity_scope": {
                field: _decision(answers, f"business_facts.entity_scope.{field}", origins.get(f"business_facts.entity_scope.{field}", revision))
                for field in _SCOPE
            },
            **{
                field: _decision(answers, f"business_facts.{field}", origins.get(f"business_facts.{field}", revision))
                for field in _FACTS
            },
        },
        "origin": {"contract": handoff["contract"], "version": handoff["version"], "defaults": {}},
    }
    try:
        request["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1_1(request)
        return validate_policy_request_v1_1(
            request, expected_context_id=context_id, expected_tenant_id=tenant_id,
            expected_plan_revision_id=handoff["plan_revision_id"],
            expected_snapshot_hash=request["approved_context"]["snapshot_hash"],
        )
    except PolicyRequestError as exc:
        raise PolicyInputError(exc.code, exc.field) from exc


def approved_request_is_current(context: dict, handoff: dict, *, tenant_id: str) -> bool:
    """Invalidate approval on any material answer, plan, or handoff change."""
    state = context.get("policy_input") or {}
    approval = state.get("approval") or {}
    if (approval.get("revision") != state.get("revision")
            or approval.get("answer_snapshot") != state.get("answers")
            or not approval.get("request")):
        return False
    try:
        current = build_approved_request(context, handoff, tenant_id=tenant_id)
    except (PolicyInputError, KeyError, TypeError, ValueError):
        return False
    return current == approval["request"]
