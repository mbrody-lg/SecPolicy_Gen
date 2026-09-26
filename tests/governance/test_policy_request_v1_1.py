"""Synthetic compatibility, provenance, and tamper tests for PolicyRequest 1.1."""

import importlib.util
import json
from pathlib import Path

import pytest

from contracts.policy_request_v1 import (
    PolicyRequestError,
    compute_policy_input_hash_v1_1,
    validate_policy_request_v1,
    validate_policy_request_v1_1,
)

GOLDEN = Path(__file__).parents[1] / "fixtures" / "policy_request_v1_1.golden.json"
GOLDEN_V1 = Path(__file__).parents[1] / "fixtures" / "policy_request_v1.golden.json"
SCOPE_PARTS = (
    "legal_entities", "size_band", "jurisdictions", "sectors", "services",
    "data_categories",
)
INTENT_FIELDS = (
    "policy_type", "scope", "audience", "exclusions", "requested_instruments",
    "document_profile", "coverage_mode", "language",
)
FACT_FIELDS = (
    "current_posture", "target_posture", "maturity", "risk_appetite",
    "risk_tolerance", "existing_controls", "known_gaps", "constraints",
    "governance_owner", "business_priorities", "critical_processes",
)
DECISION_PATHS = (
    *(('policy_intent', field) for field in INTENT_FIELDS),
    *(('business_facts', field) for field in FACT_FIELDS),
    *(('business_facts', 'entity_scope', field) for field in SCOPE_PARTS),
)


@pytest.fixture
def request_v1_1():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _rehash(request):
    request["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1_1(request)


def _decision_at(request, path):
    decision = request
    for part in path:
        decision = decision[part]
    return decision


def test_golden_round_trip_and_authoritative_binding(request_v1_1):
    approved = request_v1_1["approved_context"]
    validated = validate_policy_request_v1_1(
        request_v1_1,
        expected_context_id="synthetic-context-001",
        expected_tenant_id="synthetic-tenant-001",
        expected_plan_revision_id="synthetic-plan-001",
        expected_snapshot_hash="05f95058d677e585fb519bb359cc474f90ca4cf3ff8b64e7eefc987d6fceeb31",
    )
    assert validated == request_v1_1
    assert compute_policy_input_hash_v1_1(validated) == approved["snapshot_hash"]
    validated["business_facts"]["critical_processes"]["value"].append("Tampered")
    assert request_v1_1["business_facts"]["critical_processes"]["value"] == [
        "Customer onboarding", "Incident response",
    ]


@pytest.mark.parametrize("path", DECISION_PATHS)
def test_confidence_is_required_on_every_v1_1_decision(request_v1_1, path):
    _decision_at(request_v1_1, path).pop("confidence")
    with pytest.raises(PolicyRequestError) as error:
        validate_policy_request_v1_1(request_v1_1)
    assert error.value.code == "missing_field"
    assert error.value.field == f"$.{'.'.join(path)}.confidence"


@pytest.mark.parametrize("path", DECISION_PATHS)
def test_confidence_rejects_values_outside_enum(request_v1_1, path):
    _decision_at(request_v1_1, path)["confidence"] = 0.99
    with pytest.raises(PolicyRequestError) as error:
        validate_policy_request_v1_1(request_v1_1)
    assert error.value.code == "invalid_confidence"


def test_confidence_tamper_invalidates_exact_approval(request_v1_1):
    decision = request_v1_1["business_facts"]["business_priorities"]
    decision["confidence"] = "qualified"
    with pytest.raises(PolicyRequestError, match="snapshot_mismatch"):
        validate_policy_request_v1_1(request_v1_1)
    _rehash(request_v1_1)
    assert validate_policy_request_v1_1(request_v1_1) == request_v1_1


def test_golden_handoff_matches_context_agent_validator(request_v1_1):
    module_path = Path(__file__).parents[2] / "context-agent" / "app" / "policy_handoff_contract.py"
    spec = importlib.util.spec_from_file_location("context_agent_policy_handoff_contract_v1_1", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.validate_policy_handoff_context(
        request_v1_1["approved_context"]["policy_handoff_context"]
    ) == {"success": True}


@pytest.mark.parametrize("field", SCOPE_PARTS)
def test_each_scope_subfield_has_independent_provenance_and_hash(request_v1_1, field):
    decision = request_v1_1["business_facts"]["entity_scope"][field]
    assert decision["source_ref"] == f"answer:entity_scope.{field}"
    decision.update(value=None, source="unknown", source_ref=None, confidence="unknown")
    with pytest.raises(PolicyRequestError, match="snapshot_mismatch"):
        validate_policy_request_v1_1(request_v1_1)
    _rehash(request_v1_1)
    assert validate_policy_request_v1_1(request_v1_1) == request_v1_1


@pytest.mark.parametrize("field", ("business_priorities", "critical_processes"))
def test_new_business_fact_changes_invalidate_approval(request_v1_1, field):
    request_v1_1["business_facts"][field]["value"].append("New fact")
    with pytest.raises(PolicyRequestError, match="snapshot_mismatch"):
        validate_policy_request_v1_1(request_v1_1)


@pytest.mark.parametrize("field", ("source", "source_ref"))
def test_provenance_change_invalidate_approval(request_v1_1, field):
    decision = request_v1_1["business_facts"]["entity_scope"]["jurisdictions"]
    decision[field] = "derived" if field == "source" else "answer:new-jurisdictions"
    with pytest.raises(PolicyRequestError, match="snapshot_mismatch"):
        validate_policy_request_v1_1(request_v1_1)


@pytest.mark.parametrize("mutate,code", [
    (lambda r: r["business_facts"].pop("business_priorities"), "missing_field"),
    (lambda r: r["business_facts"].update(extra=True), "unknown_field"),
    (lambda r: r["business_facts"]["entity_scope"].pop("services"), "missing_field"),
    (lambda r: r["business_facts"]["entity_scope"].update(extra=True), "unknown_field"),
    (lambda r: r["business_facts"]["entity_scope"]["sectors"].update(extra=True), "unknown_field"),
    (lambda r: r["business_facts"]["entity_scope"]["services"].update(source="unknown", confidence="unknown"), "unknown_has_value"),
    (lambda r: r["business_facts"]["entity_scope"]["size_band"].update(value="small", source="unknown", source_ref=None, confidence="unknown"), "unknown_has_value"),
    (lambda r: r["business_facts"]["entity_scope"]["size_band"].update(source_ref=None), "invalid_value"),
    (lambda r: r["business_facts"]["entity_scope"]["size_band"].update(value="x" * 257), "too_large"),
    (lambda r: r["business_facts"]["entity_scope"]["sectors"].update(source="inferred"), "invalid_source"),
    (lambda r: r["business_facts"]["entity_scope"]["jurisdictions"].update(value=None, source="unknown", source_ref="answer:jurisdictions", confidence="unknown"), "unknown_has_value"),
    (lambda r: r["business_facts"]["entity_scope"]["jurisdictions"].update(source="unknown"), "conflicting_confidence"),
    (lambda r: r["business_facts"]["entity_scope"]["jurisdictions"].update(confidence="unknown"), "conflicting_confidence"),
    (lambda r: r["business_facts"]["maturity"].update(confidence="confirmed"), "conflicting_confidence"),
    (lambda r: r["policy_intent"]["scope"].update(confidence="certain"), "invalid_confidence"),
    (lambda r: r["business_facts"]["critical_processes"].update(value=None), "invalid_type"),
    (lambda r: r["business_facts"]["business_priorities"].update(source="derived", source_ref=None), "invalid_value"),
    (lambda r: r["business_facts"]["entity_scope"]["legal_entities"].update(value=["Example Test Ltd", "example test ltd"]), "duplicate_value"),
    (lambda r: r["policy_intent"]["exclusions"].update(value=["entity:example test ltd"]), "conflicting_intent"),
    (lambda r: r["policy_intent"]["exclusions"].update(value=["jurisdiction:EXAMPLELAND"]), "conflicting_intent"),
    (lambda r: r["approved_context"].update(hash_scope="policy_input_v1"), "unapproved_context"),
    (lambda r: r.update(version="1.0"), "unsupported_version"),
])
def test_adversarial_mutations_fail_closed(request_v1_1, mutate, code):
    mutate(request_v1_1)
    with pytest.raises(PolicyRequestError) as error:
        validate_policy_request_v1_1(request_v1_1)
    assert error.value.code == code


def test_unknown_and_confirmed_empty_are_distinct(request_v1_1):
    scope = request_v1_1["business_facts"]["entity_scope"]
    scope["sectors"].update(value=None, source="unknown", source_ref=None, confidence="unknown")
    scope["services"].update(value=[], source="provided", source_ref="answer:no_services")
    _rehash(request_v1_1)
    assert validate_policy_request_v1_1(request_v1_1) == request_v1_1


def test_version_and_hash_scope_cannot_cross_validate(request_v1_1):
    with pytest.raises(PolicyRequestError, match="unsupported_version"):
        validate_policy_request_v1(request_v1_1)
    request_v1_1["approved_context"]["hash_scope"] = "policy_input_v1"
    with pytest.raises(PolicyRequestError, match="unapproved_context"):
        validate_policy_request_v1_1(request_v1_1)
    request_v1_1["version"] = "1.0"
    with pytest.raises(PolicyRequestError, match="unsupported_version"):
        compute_policy_input_hash_v1_1(request_v1_1)


def test_external_tenant_binding_remains_required(request_v1_1):
    with pytest.raises(PolicyRequestError, match="context_mismatch"):
        validate_policy_request_v1_1(request_v1_1, expected_tenant_id="other-tenant")


def test_v1_decisions_remain_exactly_three_fields():
    request_v1 = json.loads(GOLDEN_V1.read_text(encoding="utf-8"))
    request_v1["policy_intent"]["scope"]["confidence"] = "confirmed"
    with pytest.raises(PolicyRequestError, match="unknown_field"):
        validate_policy_request_v1(request_v1)
