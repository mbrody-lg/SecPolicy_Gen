"""Pure, bounded wire contracts for policy generation and validation.

These validators check structure and internal references, not legal applicability,
source rights, tenant authorization, or the quality of generated prose.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING

VERSION = "1.0"
MAX_BYTES = 262144
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_PREFIXES = {
    "section": "sec-", "requirement": "req-", "source_unit": "unit-",
    "evidence": "ev-", "action": "act-", "revision": "rev-",
    "coverage": "cov-", "profile": "profile-", "plan": "plan-",
    "quote": "quote-", "source": "source-", "conflict": "conflict-",
    "gap": "gap-",
}


class PolicyPackageError(ValueError):
    """Stable, non-sensitive validation error with a bounded field path."""

    def __init__(self, code: str, field: str):
        self.code = code
        self.field = field[:160]
        super().__init__(f"{code}: {self.field}")


def _fail(code: str, field: str) -> None:
    raise PolicyPackageError(code, field)


def _object(value: object, required: set[str], optional: set[str], path: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail("invalid_type", path)
    extra = set(value) - required - optional
    missing = required - set(value)
    if extra:
        _fail("unknown_field", f"{path}.*")
    if missing:
        _fail("missing_field", f"{path}.{sorted(missing)[0]}")
    return value


def _text(value: object, path: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail("invalid_value", path)
    if len(value) > maximum:
        _fail("too_large", path)
    return value


def _enum(value: object, options: set[str], path: str) -> None:
    if not isinstance(value, str) or value not in options:
        _fail("invalid_value", path)


def _id(value: object, kind: str, path: str) -> str:
    if not isinstance(value, str) or len(value) > 96 or not value.startswith(_PREFIXES[kind]) or not _ID.fullmatch(value):
        _fail("invalid_id", path)
    return value


def _hash(value: object, path: str) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        _fail("invalid_hash", path)


def _list(value: object, path: str, limit: int = 128) -> list:
    if not isinstance(value, list):
        _fail("invalid_type", path)
    if len(value) > limit:
        _fail("too_large", path)
    return value


def _ids(value: object, kind: str, path: str, limit: int = 128) -> set[str]:
    items = _list(value, path, limit)
    result = [_id(item, kind, f"{path}[{index}]") for index, item in enumerate(items)]
    if len(result) != len(set(result)):
        _fail("duplicate_id", path)
    return set(result)


def _records(value: object, kind: str, path: str, required: set[str], optional: set[str] | None = None) -> tuple[list[dict], set[str]]:
    records = _list(value, path)
    seen: set[str] = set()
    for index, record in enumerate(records):
        field = f"{path}[{index}]"
        _object(record, {"id"} | required, optional or set(), field)
        identifier = _id(record["id"], kind, f"{field}.id")
        if identifier in seen:
            _fail("duplicate_id", f"{field}.id")
        seen.add(identifier)
    return records, seen


def _refs(refs: set[str], available: set[str], path: str) -> None:
    if not refs <= available:
        _fail("unknown_reference", path)


def _money(value: object, path: str, *, places: int = 2) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(
        rf"(?:0|[1-9][0-9]{{0,8}})\.[0-9]{{{places}}}", value
    ):
        _fail("invalid_amount", path)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PolicyPackageError("invalid_amount", path) from exc


def _root(value: object, contract: str, required: set[str]) -> dict:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise PolicyPackageError("invalid_json", "$") from exc
    if len(encoded) > MAX_BYTES:
        _fail("too_large", "$")
    data = _object(value, {"contract", "version"} | required, set(), "$")
    if data["contract"] != contract:
        _fail("invalid_contract", "$.contract")
    if data["version"] != VERSION:
        _fail("unsupported_version", "$.version")
    return data


def validate_generation_profile_v1(value: object) -> dict:
    """Validate presentation, coverage, and effort as independent decisions."""
    data = _root(value, "secpolicy.generation_profile", {
        "id", "policy_request_hash", "document_profile", "coverage_mode",
        "effort_tier", "language", "generation_limits",
    })
    _id(data["id"], "profile", "$.id")
    _hash(data["policy_request_hash"], "$.policy_request_hash")
    _enum(data["document_profile"], {"executive", "standard", "detailed"}, "$.document_profile")
    _enum(data["coverage_mode"], {"risk_based", "all_applicable", "full_instrument"}, "$.coverage_mode")
    _enum(data["effort_tier"], {"economy", "balanced", "assurance"}, "$.effort_tier")
    _text(data["language"], "$.language", 32)
    limits = _object(data["generation_limits"], {"max_sections", "max_requirements", "max_evidence_units"}, set(), "$.generation_limits")
    for name, maximum in (("max_sections", 64), ("max_requirements", 256), ("max_evidence_units", 256)):
        number = limits[name]
        if type(number) is not int or not 1 <= number <= maximum:
            _fail("invalid_limit", f"$.generation_limits.{name}")
    return deepcopy(data)


def validate_coverage_plan_v1(value: object) -> dict:
    """Validate dispositions and bounded coverage-to-evidence references."""
    data = _root(value, "secpolicy.coverage_plan", {
        "id", "profile_id", "policy_request_hash", "source_inventory_hash",
        "items", "conflicts", "unresolved_gaps",
    })
    _id(data["id"], "plan", "$.id")
    _id(data["profile_id"], "profile", "$.profile_id")
    _hash(data["policy_request_hash"], "$.policy_request_hash")
    _hash(data["source_inventory_hash"], "$.source_inventory_hash")
    items, _ = _records(data["items"], "coverage", "$.items", {
        "source_unit_id", "disposition", "obligation", "rationale",
        "fact_refs", "rule_ids", "evidence_ids", "requirement_ids",
        "review_disposition", "gap_ids",
    })
    if not items:
        _fail("missing_coverage", "$.items")
    gaps, gap_ids = _records(data["unresolved_gaps"], "gap", "$.unresolved_gaps", {
        "source_unit_id", "reason", "review_owner",
    })
    unit_ids = set()
    for index, item in enumerate(items):
        path = f"$.items[{index}]"
        unit_id = _id(item["source_unit_id"], "source_unit", f"{path}.source_unit_id")
        if unit_id in unit_ids:
            _fail("duplicate_id", f"{path}.source_unit_id")
        unit_ids.add(unit_id)
        _enum(item["disposition"], {"applicable", "conditional", "not_applicable", "undetermined"}, f"{path}.disposition")
        _enum(item["obligation"], {"mandatory", "optional"}, f"{path}.obligation")
        _text(item["rationale"], f"{path}.rationale")
        for name in ("fact_refs", "rule_ids"):
            for j, ref in enumerate(_list(item[name], f"{path}.{name}", 32)):
                _text(ref, f"{path}.{name}[{j}]", 96)
        _ids(item["evidence_ids"], "evidence", f"{path}.evidence_ids")
        reqs = _ids(item["requirement_ids"], "requirement", f"{path}.requirement_ids")
        _enum(item["review_disposition"], {"none", "review_required"}, f"{path}.review_disposition")
        linked_gaps = _ids(item["gap_ids"], "gap", f"{path}.gap_ids")
        _refs(linked_gaps, gap_ids, f"{path}.gap_ids")
        if (item["review_disposition"] == "review_required") != bool(linked_gaps):
            _fail("invalid_review_disposition", f"{path}.gap_ids")
        if (item["obligation"] == "mandatory"
                and item["disposition"] in {"conditional", "undetermined"}
                and item["review_disposition"] != "review_required"):
            _fail("missing_review", f"{path}.review_disposition")
        if item["disposition"] == "applicable" and item["obligation"] == "mandatory" and not reqs:
            _fail("missing_requirement", f"{path}.requirement_ids")
        if item["disposition"] in {"not_applicable", "undetermined"} and reqs:
            _fail("conflicting_disposition", f"{path}.requirement_ids")
    conflicts, _ = _records(data["conflicts"], "conflict", "$.conflicts", {"source_unit_ids", "reason", "resolution"})
    for index, conflict in enumerate(conflicts):
        path = f"$.conflicts[{index}]"
        _refs(_ids(conflict["source_unit_ids"], "source_unit", f"{path}.source_unit_ids"), unit_ids, f"{path}.source_unit_ids")
        _text(conflict["reason"], f"{path}.reason")
        _enum(conflict["resolution"], {"review_required", "resolved"}, f"{path}.resolution")
    for index, gap in enumerate(gaps):
        path = f"$.unresolved_gaps[{index}]"
        _refs({_id(gap["source_unit_id"], "source_unit", f"{path}.source_unit_id")}, unit_ids, f"{path}.source_unit_id")
        _text(gap["reason"], f"{path}.reason")
        _text(gap["review_owner"], f"{path}.review_owner", 256)
        matching_items = [item for item in items if item["source_unit_id"] == gap["source_unit_id"]]
        if not matching_items or gap["id"] not in matching_items[0]["gap_ids"]:
            _fail("unlinked_gap", f"{path}.id")
    for item in items:
        if any(gap["source_unit_id"] != item["source_unit_id"] for gap in gaps if gap["id"] in item["gap_ids"]):
            _fail("conflicting_reference", "$.items.gap_ids")
    return deepcopy(data)


def validate_policy_package_v1(value: object) -> dict:
    """Validate a structured proposal; prose rendering is not authoritative."""
    data = _root(value, "secpolicy.policy_package", {
        "revision_id", "previous_revision_id", "profile_id", "coverage_plan_id",
        "policy_request_hash", "purpose", "scope", "sections", "requirements",
        "evidence", "actions", "assumptions", "exclusions", "conflicts",
        "exception_process", "review_cadence", "provenance", "errors",
    })
    _id(data["revision_id"], "revision", "$.revision_id")
    if data["previous_revision_id"] is not None:
        _id(data["previous_revision_id"], "revision", "$.previous_revision_id")
        if data["previous_revision_id"] == data["revision_id"]:
            _fail("conflicting_revision", "$.previous_revision_id")
    _id(data["profile_id"], "profile", "$.profile_id")
    _id(data["coverage_plan_id"], "plan", "$.coverage_plan_id")
    _hash(data["policy_request_hash"], "$.policy_request_hash")
    for name in ("purpose", "scope", "exception_process", "review_cadence"):
        _text(data[name], f"$.{name}")
    sections, section_ids = _records(data["sections"], "section", "$.sections", {"title", "body", "requirement_ids"})
    requirements, requirement_ids = _records(data["requirements"], "requirement", "$.requirements", {
        "section_id", "coverage_id", "obligation", "statement", "rationale",
        "owner", "evidence_ids", "action_ids", "no_action_reason",
    })
    evidence, evidence_ids = _records(data["evidence"], "evidence", "$.evidence", {
        "source_id", "source_unit_id", "source_version", "source_digest",
        "locator", "corpus_status", "excerpt_digest", "role", "candidate_reason",
    })
    actions, action_ids = _records(data["actions"], "action", "$.actions", {
        "requirement_id", "owner", "trigger", "target", "completion_evidence",
    })
    if not sections or not requirements:
        _fail("empty_package", "$.sections")
    for index, section in enumerate(sections):
        path = f"$.sections[{index}]"
        _text(section["title"], f"{path}.title", 256)
        _text(section["body"], f"{path}.body", 12000)
        _refs(_ids(section["requirement_ids"], "requirement", f"{path}.requirement_ids"), requirement_ids, f"{path}.requirement_ids")
    requirement_sections = {item["id"]: item["section_id"] for item in requirements}
    for index, requirement in enumerate(requirements):
        path = f"$.requirements[{index}]"
        section_id = _id(requirement["section_id"], "section", f"{path}.section_id")
        _refs({section_id}, section_ids, f"{path}.section_id")
        _id(requirement["coverage_id"], "coverage", f"{path}.coverage_id")
        _enum(requirement["obligation"], {"mandatory", "optional"}, f"{path}.obligation")
        for name in ("statement", "rationale", "owner"):
            _text(requirement[name], f"{path}.{name}")
        _refs(_ids(requirement["evidence_ids"], "evidence", f"{path}.evidence_ids"), evidence_ids, f"{path}.evidence_ids")
        _refs(_ids(requirement["action_ids"], "action", f"{path}.action_ids"), action_ids, f"{path}.action_ids")
        if requirement["action_ids"]:
            if requirement["no_action_reason"] is not None:
                _fail("conflicting_action", f"{path}.no_action_reason")
        else:
            _text(requirement["no_action_reason"], f"{path}.no_action_reason")
        if requirement["obligation"] == "mandatory" and not requirement["evidence_ids"]:
            _fail("missing_evidence", f"{path}.evidence_ids")
        if requirement["id"] not in next(s["requirement_ids"] for s in sections if s["id"] == section_id):
            _fail("missing_reference", f"{path}.section_id")
    for index, section in enumerate(sections):
        if any(requirement_sections[requirement_id] != section["id"] for requirement_id in section["requirement_ids"]):
            _fail("conflicting_reference", f"$.sections[{index}].requirement_ids")
    for index, item in enumerate(evidence):
        path = f"$.evidence[{index}]"
        _id(item["source_id"], "source", f"{path}.source_id")
        _id(item["source_unit_id"], "source_unit", f"{path}.source_unit_id")
        for name in ("source_digest", "excerpt_digest"):
            _hash(item[name], f"{path}.{name}")
        for name in ("source_version", "locator"):
            _text(item[name], f"{path}.{name}", 256)
        _enum(item["corpus_status"], {"synthetic", "rights_verified"}, f"{path}.corpus_status")
        _enum(item["role"], {"grounding", "candidate"}, f"{path}.role")
        if item["role"] == "candidate":
            _text(item["candidate_reason"], f"{path}.candidate_reason")
        elif item["candidate_reason"] is not None:
            _fail("invalid_value", f"{path}.candidate_reason")
    for index, action in enumerate(actions):
        path = f"$.actions[{index}]"
        requirement_id = _id(action["requirement_id"], "requirement", f"{path}.requirement_id")
        _refs({requirement_id}, requirement_ids, f"{path}.requirement_id")
        for name in ("owner", "trigger", "target", "completion_evidence"):
            _text(action[name], f"{path}.{name}")
        if action["id"] not in next(r["action_ids"] for r in requirements if r["id"] == requirement_id):
            _fail("missing_reference", f"{path}.requirement_id")
    for index, assumption in enumerate(_list(data["assumptions"], "$.assumptions", 64)):
        _text(assumption, f"$.assumptions[{index}]")
    for index, exclusion in enumerate(_list(data["exclusions"], "$.exclusions", 64)):
        path = f"$.exclusions[{index}]"
        _object(exclusion, {"kind", "target_id", "reason"}, set(), path)
        _enum(exclusion["kind"], {"entity", "jurisdiction", "instrument", "source_unit"}, f"{path}.kind")
        _text(exclusion["target_id"], f"{path}.target_id", 96)
        _text(exclusion["reason"], f"{path}.reason")
    conflicts, _ = _records(data["conflicts"], "conflict", "$.conflicts", {"source_unit_ids", "reason", "resolution"})
    for index, conflict in enumerate(conflicts):
        path = f"$.conflicts[{index}]"
        _ids(conflict["source_unit_ids"], "source_unit", f"{path}.source_unit_ids")
        _text(conflict["reason"], f"{path}.reason")
        _enum(conflict["resolution"], {"review_required", "resolved"}, f"{path}.resolution")
    provenance = _object(data["provenance"], {"context_revision_id", "source_inventory_hash", "generator_version"}, set(), "$.provenance")
    _id(provenance["context_revision_id"], "revision", "$.provenance.context_revision_id")
    _hash(provenance["source_inventory_hash"], "$.provenance.source_inventory_hash")
    _text(provenance["generator_version"], "$.provenance.generator_version", 96)
    for index, error in enumerate(_list(data["errors"], "$.errors", 32)):
        path = f"$.errors[{index}]"
        _object(error, {"code", "stage", "reference_id"}, set(), path)
        _enum(error["code"], {"missing_evidence", "unresolved_applicability", "source_conflict", "budget_blocked", "generation_failed"}, f"{path}.code")
        _enum(error["stage"], {"coverage", "retrieval", "generation", "validation"}, f"{path}.stage")
        if error["reference_id"] is not None:
            _text(error["reference_id"], f"{path}.reference_id", 96)
    return deepcopy(data)


def validate_generation_budget_quote_v1(value: object) -> dict:
    """Validate a non-authorizing estimate; runtime reservations are separate."""
    data = _root(value, "secpolicy.generation_budget_quote", {
        "id", "profile_id", "coverage_plan_id", "policy_request_hash",
        "price_catalog_version", "currency", "estimated_amount", "unrounded_upper_bound", "reserved_upper_bound",
        "run_cap", "estimated_calls", "max_calls", "estimated_tokens", "max_tokens",
        "status", "reason_code",
    })
    _id(data["id"], "quote", "$.id")
    _id(data["profile_id"], "profile", "$.profile_id")
    _id(data["coverage_plan_id"], "plan", "$.coverage_plan_id")
    _hash(data["policy_request_hash"], "$.policy_request_hash")
    _text(data["price_catalog_version"], "$.price_catalog_version", 96)
    if not isinstance(data["currency"], str) or not _CURRENCY.fullmatch(data["currency"]):
        _fail("invalid_currency", "$.currency")
    amounts = {
        "estimated_amount": _money(data["estimated_amount"], "$.estimated_amount", places=6),
        "unrounded_upper_bound": _money(data["unrounded_upper_bound"], "$.unrounded_upper_bound", places=6),
        "reserved_upper_bound": _money(data["reserved_upper_bound"], "$.reserved_upper_bound"),
        "run_cap": _money(data["run_cap"], "$.run_cap"),
    }
    if amounts["estimated_amount"] > amounts["unrounded_upper_bound"]:
        _fail("invalid_budget_order", "$.unrounded_upper_bound")
    rounded = amounts["unrounded_upper_bound"].quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    if amounts["reserved_upper_bound"] != rounded:
        _fail("invalid_rounding", "$.reserved_upper_bound")
    for name, limit in (("estimated_calls", 128), ("max_calls", 128), ("estimated_tokens", 10000000), ("max_tokens", 10000000)):
        number = data[name]
        if type(number) is not int or not 0 <= number <= limit:
            _fail("invalid_limit", f"$.{name}")
    if data["estimated_calls"] > data["max_calls"] or data["estimated_tokens"] > data["max_tokens"]:
        _fail("invalid_budget_order", "$.max_calls")
    _enum(data["status"], {"estimate_only", "blocked"}, "$.status")
    if data["status"] == "blocked":
        _enum(data["reason_code"], {"insufficient_budget", "unknown_price", "missing_scope", "unavailable_provider"}, "$.reason_code")
        if data["reason_code"] == "insufficient_budget" and amounts["reserved_upper_bound"] <= amounts["run_cap"]:
            _fail("invalid_budget_order", "$.run_cap")
    elif data["reason_code"] is not None:
        _fail("invalid_value", "$.reason_code")
    elif amounts["reserved_upper_bound"] > amounts["run_cap"]:
        _fail("invalid_budget_order", "$.run_cap")
    return deepcopy(data)


def validate_package_bundle_v1(profile: object, plan: object, package: object, quote: object) -> tuple[dict, dict, dict, dict]:
    """Check cross-contract identity, coverage and evidence without parsing prose."""
    checked = (validate_generation_profile_v1(profile), validate_coverage_plan_v1(plan),
               validate_policy_package_v1(package), validate_generation_budget_quote_v1(quote))
    profile_data, plan_data, package_data, quote_data = checked
    request_hash = profile_data["policy_request_hash"]
    if any(part["policy_request_hash"] != request_hash for part in checked):
        _fail("binding_mismatch", "$.policy_request_hash")
    if any(part["profile_id"] != profile_data["id"] for part in checked[1:]):
        _fail("binding_mismatch", "$.profile_id")
    if package_data["coverage_plan_id"] != plan_data["id"] or quote_data["coverage_plan_id"] != plan_data["id"]:
        _fail("binding_mismatch", "$.coverage_plan_id")
    if package_data["provenance"]["source_inventory_hash"] != plan_data["source_inventory_hash"]:
        _fail("binding_mismatch", "$.source_inventory_hash")
    plan_items = {item["id"]: item for item in plan_data["items"]}
    requirements = {item["id"]: item for item in package_data["requirements"]}
    evidence = {item["id"]: item for item in package_data["evidence"]}
    plan_unit_ids = {item["source_unit_id"] for item in plan_items.values()}
    planned_evidence_ids = {evidence_id for item in plan_items.values() for evidence_id in item["evidence_ids"]}
    used_evidence_ids = {evidence_id for requirement in requirements.values() for evidence_id in requirement["evidence_ids"]}
    for evidence_id, record in evidence.items():
        if record["role"] == "candidate":
            if (record["source_unit_id"] in plan_unit_ids or evidence_id in planned_evidence_ids
                    or evidence_id in used_evidence_ids):
                _fail("candidate_used_as_grounding", "$.evidence")
        elif record["source_unit_id"] not in plan_unit_ids or evidence_id not in planned_evidence_ids:
            _fail("unplanned_evidence", "$.evidence")
    for requirement in requirements.values():
        item = plan_items.get(requirement["coverage_id"])
        if item is None or requirement["id"] not in item["requirement_ids"] or requirement["obligation"] != item["obligation"]:
            _fail("coverage_mismatch", "$.requirements")
        if not set(requirement["evidence_ids"]) <= set(item["evidence_ids"]):
            _fail("coverage_mismatch", "$.requirements.evidence_ids")
    for item in plan_items.values():
        _refs(set(item["requirement_ids"]), set(requirements), "$.items.requirement_ids")
        _refs(set(item["evidence_ids"]), set(evidence), "$.items.evidence_ids")
        for requirement_id in item["requirement_ids"]:
            if requirements[requirement_id]["coverage_id"] != item["id"]:
                _fail("coverage_mismatch", "$.items.requirement_ids")
        for evidence_id in item["evidence_ids"]:
            if evidence[evidence_id]["source_unit_id"] != item["source_unit_id"] or evidence[evidence_id]["role"] != "grounding":
                _fail("coverage_mismatch", "$.items.evidence_ids")
    limits = profile_data["generation_limits"]
    for count, limit in ((len(package_data["sections"]), "max_sections"),
                         (len(package_data["requirements"]), "max_requirements"),
                         (len(package_data["evidence"]), "max_evidence_units")):
        if count > limits[limit]:
            _fail("too_large", f"$.generation_limits.{limit}")
    return checked
