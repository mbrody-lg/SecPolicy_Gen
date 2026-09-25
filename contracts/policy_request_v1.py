"""Pure canonical Policy request validation and conservative v0 projection."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256

CONTRACT = "secpolicy.policy_request"
VERSION = "1.0"
MAX_BYTES = 65536
_HASH = re.compile(r"^[0-9a-f]{64}$")
_POLICY_INTENT = {
    "policy_type": "string",
    "scope": "string",
    "audience": "strings",
    "exclusions": "exclusions",
    "requested_instruments": "instruments",
    "document_profile": "profile",
    "coverage_mode": "coverage",
    "language": "string",
}
_BUSINESS_FACTS = {
    "entity_scope": "entity_scope",
    "current_posture": "string",
    "target_posture": "string",
    "maturity": "string",
    "risk_appetite": "string",
    "risk_tolerance": "string",
    "existing_controls": "strings",
    "known_gaps": "strings",
    "constraints": "strings",
    "governance_owner": "string",
}
_MANDATORY = {"policy_type", "scope", "audience", "document_profile", "coverage_mode", "language"}
_PROFILES = {"executive", "standard", "detailed"}
_COVERAGE = {"risk_based", "all_applicable", "full_instrument"}
_EXCLUSION_KINDS = {"entity", "jurisdiction", "instrument"}


class PolicyRequestError(ValueError):
    """A contract violation with a stable code and field path."""

    def __init__(self, code: str, field: str):
        super().__init__(f"{code}: {field}")
        self.code = code
        self.field = field


def _fail(code: str, field: str) -> None:
    raise PolicyRequestError(code, field)


def _keys(value: object, allowed: set[str], required: set[str], field: str) -> dict:
    if not isinstance(value, dict):
        _fail("invalid_type", field)
    if any(not isinstance(key, str) for key in value):
        _fail("invalid_type", field)
    extra = set(value) - allowed
    if extra:
        _fail("unknown_field", f"{field}.{sorted(extra)[0]}")
    missing = required - set(value)
    if missing:
        _fail("missing_field", f"{field}.{sorted(missing)[0]}")
    return value


def _text(value: object, field: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail("invalid_value", field)
    if len(value) > max_length:
        _fail("too_large", field)
    return value


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        _fail("invalid_type", field)
    if len(value) > 32:
        _fail("too_large", field)
    for index, item in enumerate(value):
        _text(item, f"{field}[{index}]", max_length=512)
    if len(set(value)) != len(value):
        _fail("duplicate_value", field)
    return value


def _exclusions(value: object, field: str) -> list[str]:
    entries = _strings(value, field)
    normalized = set()
    for index, entry in enumerate(entries):
        kind, separator, identifier = entry.partition(":")
        if (separator != ":" or kind not in _EXCLUSION_KINDS
                or not identifier or identifier != identifier.strip()):
            _fail("invalid_value", f"{field}[{index}]")
        identity = (kind, identifier.casefold())
        if identity in normalized:
            _fail("duplicate_value", field)
        normalized.add(identity)
    return entries


def _value(value: object, kind: str, field: str) -> None:
    if kind == "string":
        _text(value, field, max_length=2000)
    elif kind == "strings":
        _strings(value, field)
    elif kind == "exclusions":
        _exclusions(value, field)
    elif kind == "profile":
        if not isinstance(value, str) or value not in _PROFILES:
            _fail("invalid_value", field)
    elif kind == "coverage":
        if not isinstance(value, str) or value not in _COVERAGE:
            _fail("invalid_value", field)
    elif kind == "entity_scope":
        scope = _keys(value,
                      {"legal_entities", "size_band", "jurisdictions", "sectors", "services", "data_categories"},
                      {"legal_entities", "size_band", "jurisdictions", "sectors", "services", "data_categories"}, field)
        for part in ("legal_entities", "jurisdictions", "sectors", "services", "data_categories"):
            _strings(scope[part], f"{field}.{part}")
        if scope["size_band"] is not None:
            _text(scope["size_band"], f"{field}.size_band")
    elif kind == "instruments":
        if not isinstance(value, list) or len(value) > 32:
            _fail("invalid_type" if not isinstance(value, list) else "too_large", field)
        ids = []
        for index, item in enumerate(value):
            path = f"{field}[{index}]"
            item = _keys(item, {"id", "version"}, {"id"}, path)
            ids.append(_text(item["id"], f"{path}.id"))
            if "version" in item and item["version"] is not None:
                _text(item["version"], f"{path}.version")
        if len(ids) != len(set(ids)):
            _fail("duplicate_value", field)


def _decision(value: object, kind: str, field: str) -> dict:
    decision = _keys(value, {"value", "source", "source_ref"},
                     {"value", "source", "source_ref"}, field)
    source = decision["source"]
    if source not in ("provided", "derived", "unknown"):
        _fail("invalid_source", f"{field}.source")
    if source == "unknown":
        if decision["value"] is not None or decision["source_ref"] is not None:
            _fail("unknown_has_value", field)
    else:
        _text(decision["source_ref"], f"{field}.source_ref")
        _value(decision["value"], kind, f"{field}.value")
    return decision


def compute_policy_input_hash_v1(request: dict) -> str:
    """Hash the exact generation inputs, excluding mutable approval metadata."""
    approved = request["approved_context"]
    preimage = {
        "contract": request["contract"],
        "version": request["version"],
        "context_id": request["context_id"],
        "tenant_id": approved["tenant_id"],
        "plan_revision_id": approved["plan_revision_id"],
        "legacy_handoff_hash": approved["legacy_handoff_hash"],
        "policy_handoff_context": approved["policy_handoff_context"],
        "policy_intent": request["policy_intent"],
        "business_facts": request["business_facts"],
        "origin": request["origin"],
    }
    canonical = json.dumps(
        preimage, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def validate_policy_request_v1(
    request: object, *, expected_context_id: str | None = None,
    expected_tenant_id: str | None = None, expected_plan_revision_id: str | None = None,
    expected_snapshot_hash: str | None = None,
) -> dict:
    """Validate an approved, complete v1 request and return a defensive copy."""
    try:
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise PolicyRequestError("invalid_json", "$") from exc
    if len(encoded) > MAX_BYTES:
        _fail("too_large", "$")
    fields = {"contract", "version", "context_id", "approved_context", "policy_intent", "business_facts", "origin"}
    data = _keys(request, fields, fields, "$")
    if data["contract"] != CONTRACT:
        _fail("invalid_contract", "$.contract")
    if data["version"] != VERSION:
        _fail("unsupported_version", "$.version")
    context_id = _text(data["context_id"], "$.context_id")
    approved = _keys(data["approved_context"],
                     {"approval_status", "context_id", "tenant_id", "plan_revision_id", "snapshot_hash", "legacy_handoff_hash", "hash_scope", "policy_handoff_context"},
                     {"approval_status", "context_id", "tenant_id", "plan_revision_id", "snapshot_hash", "legacy_handoff_hash", "hash_scope", "policy_handoff_context"},
                     "$.approved_context")
    if approved["approval_status"] != "approved" or approved["hash_scope"] != "policy_input_v1":
        _fail("unapproved_context", "$.approved_context.approval_status")
    if approved["context_id"] != context_id:
        _fail("context_mismatch", "$.approved_context.context_id")
    for field in ("tenant_id", "plan_revision_id"):
        _text(approved[field], f"$.approved_context.{field}")
    if not isinstance(approved["snapshot_hash"], str) or not _HASH.fullmatch(approved["snapshot_hash"]):
        _fail("invalid_hash", "$.approved_context.snapshot_hash")
    if not isinstance(approved["legacy_handoff_hash"], str) or not _HASH.fullmatch(approved["legacy_handoff_hash"]):
        _fail("invalid_hash", "$.approved_context.legacy_handoff_hash")
    handoff = _keys(approved["policy_handoff_context"],
                    set(approved["policy_handoff_context"]) if isinstance(approved["policy_handoff_context"], dict) else set(),
                    {"contract", "version", "source", "plan_revision_id", "context_snapshot_hash",
                     "security_context_version", "final_context_version",
                     "final_context_status", "context_ready_for_policy", "final_context_sections",
                     "structured_findings", "retrieval_hints", "unresolved_gaps"},
                    "$.approved_context.policy_handoff_context")
    if (handoff["contract"] != "context_agent.policy_handoff" or handoff["version"] != "1.0"
            or handoff["source"] != "context-agent"
            or handoff["security_context_version"] != "1.0"
            or handoff["final_context_version"] != "1.0"):
        _fail("unsupported_handoff", "$.approved_context.policy_handoff_context")
    if (handoff["plan_revision_id"] != approved["plan_revision_id"]
            or handoff["context_snapshot_hash"] != approved["legacy_handoff_hash"]):
        _fail("snapshot_mismatch", "$.approved_context.policy_handoff_context")
    if (handoff["final_context_status"] != "ready" or handoff["context_ready_for_policy"] is not True
            or handoff["unresolved_gaps"] != []):
        _fail("unapproved_context", "$.approved_context.policy_handoff_context")
    sections = handoff["final_context_sections"]
    if not isinstance(sections, dict) or not sections or any(
        not isinstance(section, dict) or section.get("status") != "accepted" or not section.get("content")
        for section in sections.values()
    ):
        _fail("unapproved_context", "$.approved_context.policy_handoff_context.final_context_sections")
    if not isinstance(handoff["structured_findings"], list) or not handoff["structured_findings"]:
        _fail("unapproved_context", "$.approved_context.policy_handoff_context.structured_findings")
    for finding in handoff["structured_findings"]:
        if not isinstance(finding, dict) or finding.get("status") != "completed" or not finding.get("task_id"):
            _fail("unapproved_context", "$.approved_context.policy_handoff_context.structured_findings")
        evidence = any(isinstance(finding.get(field), list) and any(
            isinstance(item, str) and item.strip() for item in finding[field]
        ) for field in ("findings", "risks", "policy_implications"))
        if not evidence and not (isinstance(finding.get("content"), str) and finding["content"].strip()):
            _fail("unapproved_context", "$.approved_context.policy_handoff_context.structured_findings")
    hints = handoff["retrieval_hints"]
    if not isinstance(hints, dict) or not _strings(hints.get("collection_families"),
                                                   "$.approved_context.policy_handoff_context.retrieval_hints.collection_families"):
        _fail("unapproved_context", "$.approved_context.policy_handoff_context.retrieval_hints")
    for field, expected in (("context_id", expected_context_id),
                            ("tenant_id", expected_tenant_id),
                            ("plan_revision_id", expected_plan_revision_id),
                            ("snapshot_hash", expected_snapshot_hash)):
        actual = context_id if field == "context_id" else approved[field]
        if expected is not None and actual != expected:
            _fail("context_mismatch", f"$.approved_context.{field}")
    origin = _keys(data["origin"], {"contract", "version", "defaults"},
                   {"contract", "version", "defaults"}, "$.origin")
    _text(origin["contract"], "$.origin.contract")
    _text(origin["version"], "$.origin.version")
    if origin["contract"] != handoff["contract"] or origin["version"] != handoff["version"]:
        _fail("origin_mismatch", "$.origin")
    defaults = _keys(origin["defaults"], {"document_profile", "coverage_mode"}, set(), "$.origin.defaults")
    intent = _keys(data["policy_intent"], set(_POLICY_INTENT), set(_POLICY_INTENT), "$.policy_intent")
    for field, kind in _POLICY_INTENT.items():
        decision = _decision(intent[field], kind, f"$.policy_intent.{field}")
        if field in _MANDATORY and decision["source"] == "unknown":
            _fail("unresolved_intent", f"$.policy_intent.{field}")
        if field == "audience" and not decision["value"]:
            _fail("unresolved_intent", "$.policy_intent.audience")
        if field in defaults and (decision["source"] != "derived" or decision["value"] != defaults[field]):
            _fail("conflicting_default", f"$.policy_intent.{field}")
    facts = _keys(data["business_facts"], set(_BUSINESS_FACTS), set(_BUSINESS_FACTS), "$.business_facts")
    for field, kind in _BUSINESS_FACTS.items():
        _decision(facts[field], kind, f"$.business_facts.{field}")
    if (intent["coverage_mode"]["value"] == "full_instrument"
            and (intent["requested_instruments"]["source"] == "unknown"
                 or not intent["requested_instruments"]["value"])):
        _fail("unresolved_intent", "$.policy_intent.requested_instruments")
    excluded = {(kind, identifier.casefold()) for kind, identifier in (
        entry.split(":", 1) for entry in (intent["exclusions"]["value"] or [])
    )}
    entity_scope = facts["entity_scope"]["value"] if facts["entity_scope"]["source"] != "unknown" else None
    if entity_scope and excluded.intersection(
        {("entity", entity.casefold()) for entity in entity_scope["legal_entities"]}
        | {("jurisdiction", jurisdiction.casefold()) for jurisdiction in entity_scope["jurisdictions"]}
    ):
        _fail("conflicting_intent", "$.policy_intent.exclusions")
    requested = intent["requested_instruments"]["value"] or []
    if excluded.intersection({("instrument", item["id"].casefold()) for item in requested}):
        _fail("conflicting_intent", "$.policy_intent.exclusions")
    if compute_policy_input_hash_v1(data) != approved["snapshot_hash"]:
        _fail("snapshot_mismatch", "$.approved_context.snapshot_hash")
    return deepcopy(data)


def adapt_policy_handoff_v0(handoff: object, *, context_id: str, language: str | None = None) -> dict:
    """Project a v0 handoff without asserting approval or inventing intent."""
    source = _keys(handoff, set(handoff) if isinstance(handoff, dict) else set(),
                   {"contract", "version", "source", "context_snapshot_hash"}, "handoff")
    if (source["contract"] != "context_agent.policy_handoff" or source["version"] != "1.0"
            or source["source"] != "context-agent"):
        _fail("unsupported_handoff", "handoff")
    _text(context_id, "context_id")
    snapshot_hash = source["context_snapshot_hash"]
    if not isinstance(snapshot_hash, str) or not _HASH.fullmatch(snapshot_hash):
        _fail("invalid_hash", "handoff.context_snapshot_hash")
    unknown = {"value": None, "source": "unknown", "source_ref": None}
    intent = {field: deepcopy(unknown) for field in _POLICY_INTENT}
    facts = {field: deepcopy(unknown) for field in _BUSINESS_FACTS}
    if language is not None:
        intent["language"] = {"value": _text(language, "language"),
                              "source": "provided", "source_ref": "legacy_request.language"}
    defaults = {"document_profile": "standard", "coverage_mode": "risk_based"}
    for field, value in defaults.items():
        intent[field] = {"value": value, "source": "derived", "source_ref": f"compatibility_default:{field}"}
    return {
        "contract": CONTRACT, "version": VERSION, "context_id": context_id,
        "approved_context": {
            "approval_status": "legacy_unverified", "context_id": context_id,
            "tenant_id": None, "plan_revision_id": source.get("plan_revision_id"),
            "snapshot_hash": snapshot_hash, "legacy_handoff_hash": snapshot_hash,
            "hash_scope": "legacy_plan_subset_v1",
            "policy_handoff_context": deepcopy(source),
        },
        "policy_intent": intent,
        "business_facts": facts,
        "origin": {"contract": source["contract"], "version": source["version"], "defaults": defaults},
    }
