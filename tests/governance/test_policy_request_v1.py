"""Synthetic goldens and adversarial mutations for the future Policy request."""

import json
import importlib.util
from pathlib import Path

import pytest

from contracts.policy_request_v1 import (
    PolicyRequestError,
    adapt_policy_handoff_v0,
    compute_policy_input_hash_v1,
    validate_policy_request_v1,
)

GOLDEN = Path(__file__).parents[1] / "fixtures" / "policy_request_v1.golden.json"


@pytest.fixture
def request_v1():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_round_trip_and_authoritative_binding(request_v1):
    validated = validate_policy_request_v1(
        request_v1,
        expected_context_id="synthetic-context-001",
        expected_tenant_id="synthetic-tenant-001",
        expected_plan_revision_id="synthetic-plan-001",
        expected_snapshot_hash="bfa1f606502f3c49a2b93fd8538556a51c3aee2ffe9c857caab87b600bec655d",
    )
    assert json.loads(json.dumps(validated)) == request_v1
    assert compute_policy_input_hash_v1(validated) == request_v1["approved_context"]["snapshot_hash"]
    validated["policy_intent"]["audience"]["value"].append("mutated")
    assert request_v1["policy_intent"]["audience"]["value"] == ["employees"]


@pytest.mark.parametrize("mutate,code", [
    (lambda r: r.update(version="2.0"), "unsupported_version"),
    (lambda r: r.update(extra=True), "unknown_field"),
    (lambda r: r.pop("business_facts"), "missing_field"),
    (lambda r: r.pop("origin"), "missing_field"),
    (lambda r: r["policy_intent"].update(extra={}), "unknown_field"),
    (lambda r: r["business_facts"].update(extra={}), "unknown_field"),
    (lambda r: r["policy_intent"].pop("policy_type"), "missing_field"),
    (lambda r: r["policy_intent"]["policy_type"].update(value=None, source="unknown", source_ref=None), "unresolved_intent"),
    (lambda r: r["policy_intent"]["language"].update(source="unknown"), "unknown_has_value"),
    (lambda r: r["policy_intent"]["audience"].update(value=[]), "unresolved_intent"),
    (lambda r: r["policy_intent"]["document_profile"].update(value=[]), "invalid_value"),
    (lambda r: r["policy_intent"]["coverage_mode"].update(value={}), "invalid_value"),
    (lambda r: r["business_facts"]["entity_scope"]["value"].update(extra=True), "unknown_field"),
    (lambda r: r["approved_context"].update(extra=True), "unknown_field"),
    (lambda r: r["approved_context"].update(tenant_id=None), "invalid_value"),
    (lambda r: r["policy_intent"]["policy_type"].update(source_ref=None), "invalid_value"),
    (lambda r: r["business_facts"]["maturity"].update(value="claimed"), "unknown_has_value"),
    (lambda r: r["policy_intent"]["coverage_mode"].update(value="full_instrument"), "unresolved_intent"),
    (lambda r: r["approved_context"].update(approval_status="legacy_unverified"), "unapproved_context"),
    (lambda r: r["approved_context"].update(hash_scope="legacy_plan_subset_v1"), "unapproved_context"),
    (lambda r: r["approved_context"].update(context_id="other"), "context_mismatch"),
    (lambda r: r["approved_context"].update(snapshot_hash="bad"), "invalid_hash"),
    (lambda r: r["approved_context"].update(legacy_handoff_hash="bad"), "invalid_hash"),
    (lambda r: r["approved_context"]["policy_handoff_context"].update(plan_revision_id="other"), "snapshot_mismatch"),
    (lambda r: r["approved_context"]["policy_handoff_context"].update(context_snapshot_hash="b" * 64), "snapshot_mismatch"),
    (lambda r: r["approved_context"]["policy_handoff_context"].update(final_context_status="draft"), "unapproved_context"),
    (lambda r: r["approved_context"]["policy_handoff_context"].update(unresolved_gaps=["missing"]), "unapproved_context"),
    (lambda r: r["policy_intent"]["exclusions"].update(value=["jurisdiction:exampleland"]), "conflicting_intent"),
    (lambda r: r["policy_intent"]["exclusions"].update(value=["Exampleland"]), "invalid_value"),
    (lambda r: r["policy_intent"]["exclusions"].update(value=["jurisdiction: Exampleland"]), "invalid_value"),
    (lambda r: r["policy_intent"]["exclusions"].update(value=["instrument: synthetic-framework-x"]), "invalid_value"),
    (lambda r: r["approved_context"]["policy_handoff_context"].pop("final_context_version"), "missing_field"),
    (lambda r: r["approved_context"]["policy_handoff_context"]["structured_findings"][0].update(findings=[]), "unapproved_context"),
    (lambda r: r["business_facts"]["current_posture"].update(value="x" * 70000), "too_large"),
    (lambda r: r["origin"]["defaults"].update(document_profile="executive"), "conflicting_default"),
])
def test_mutations_fail_closed(request_v1, mutate, code):
    mutate(request_v1)
    with pytest.raises(PolicyRequestError) as error:
        validate_policy_request_v1(request_v1)
    assert error.value.code == code


@pytest.mark.parametrize("binding", [
    {"expected_context_id": "other"},
    {"expected_tenant_id": "other"},
    {"expected_plan_revision_id": "other"},
    {"expected_snapshot_hash": "b" * 64},
])
def test_external_binding_mismatch(request_v1, binding):
    with pytest.raises(PolicyRequestError, match="context_mismatch"):
        validate_policy_request_v1(request_v1, **binding)


def test_full_instrument_with_explicit_instrument(request_v1):
    request_v1["policy_intent"]["coverage_mode"]["value"] = "full_instrument"
    request_v1["policy_intent"]["requested_instruments"]["value"] = [{"id": "synthetic-framework-x", "version": "1.0"}]
    request_v1["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1(request_v1)
    assert validate_policy_request_v1(request_v1) == request_v1


def test_instrument_exclusion_conflicts_with_requested_instrument(request_v1):
    request_v1["policy_intent"]["requested_instruments"]["value"] = [{"id": "synthetic-framework-x"}]
    request_v1["policy_intent"]["exclusions"]["value"] = ["instrument:SYNTHETIC-FRAMEWORK-X"]
    request_v1["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1(request_v1)
    with pytest.raises(PolicyRequestError, match="conflicting_intent"):
        validate_policy_request_v1(request_v1)


def test_golden_handoff_matches_context_agent_validator(request_v1):
    module_path = Path(__file__).parents[2] / "context-agent" / "app" / "policy_handoff_contract.py"
    spec = importlib.util.spec_from_file_location("context_agent_policy_handoff_contract", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.validate_policy_handoff_context(
        request_v1["approved_context"]["policy_handoff_context"]
    ) == {"success": True}


def test_changed_approved_fact_cannot_reuse_snapshot_hash(request_v1):
    request_v1["business_facts"]["target_posture"]["value"] = "Monthly reviews"
    with pytest.raises(PolicyRequestError, match="snapshot_mismatch"):
        validate_policy_request_v1(request_v1)


def test_v0_adapter_cannot_manufacture_approval_or_regulatory_intent():
    handoff = {
        "contract": "context_agent.policy_handoff", "version": "1.0", "source": "context-agent",
        "plan_revision_id": "synthetic-plan-001", "context_snapshot_hash": "a" * 64,
        "business_context": {"country": "Exampleland", "need": "access controls"},
    }
    projected = adapt_policy_handoff_v0(handoff, context_id="synthetic-context-001", language="en")
    assert projected["approved_context"]["approval_status"] == "legacy_unverified"
    assert projected["approved_context"]["hash_scope"] == "legacy_plan_subset_v1"
    assert projected["approved_context"]["tenant_id"] is None
    assert projected["business_facts"]["risk_appetite"]["source"] == "unknown"
    assert projected["policy_intent"]["requested_instruments"]["source"] == "unknown"
    assert projected["policy_intent"]["document_profile"]["value"] == "standard"
    assert projected["origin"]["defaults"] == {"document_profile": "standard", "coverage_mode": "risk_based"}
    with pytest.raises(PolicyRequestError, match="unapproved_context"):
        validate_policy_request_v1(projected)


def test_v0_adapter_rejects_untrusted_hash():
    with pytest.raises(PolicyRequestError, match="invalid_hash"):
        adapt_policy_handoff_v0({
            "contract": "context_agent.policy_handoff", "version": "1.0",
            "source": "context-agent", "context_snapshot_hash": "bad",
        }, context_id="synthetic-context-001")
