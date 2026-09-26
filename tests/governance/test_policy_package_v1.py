"""Synthetic and adversarial tests for the W06 structured package contracts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from contracts.policy_package_v1 import (
    PolicyPackageError,
    validate_coverage_plan_v1,
    validate_generation_budget_quote_v1,
    validate_generation_profile_v1,
    validate_package_bundle_v1,
    validate_policy_package_v1,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "policy_package_v1.synthetic.json"
VALIDATORS = {
    "profile": validate_generation_profile_v1,
    "coverage_plan": validate_coverage_plan_v1,
    "package": validate_policy_package_v1,
    "budget_quote": validate_generation_budget_quote_v1,
}


@pytest.fixture
def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def check_bundle(bundle):
    return validate_package_bundle_v1(
        bundle["profile"], bundle["coverage_plan"], bundle["package"], bundle["budget_quote"]
    )


def test_synthetic_round_trip_and_defensive_copy(bundle):
    validated = check_bundle(bundle)
    assert json.loads(json.dumps(validated)) == [bundle[key] for key in VALIDATORS]
    validated[2]["sections"][0]["body"] = "Changed"
    assert bundle["package"]["sections"][0]["body"] != "Changed"


@pytest.mark.parametrize("name", list(VALIDATORS))
def test_each_contract_rejects_unknown_version_and_field(bundle, name):
    payload = bundle[name]
    payload["version"] = "1.1"
    with pytest.raises(PolicyPackageError) as error:
        VALIDATORS[name](payload)
    assert error.value.code == "unsupported_version"
    payload["version"] = "1.0"
    payload["unexpected"] = True
    with pytest.raises(PolicyPackageError) as error:
        VALIDATORS[name](payload)
    assert error.value.code == "unknown_field"


@pytest.mark.parametrize("name", list(VALIDATORS))
def test_each_contract_rejects_large_and_invalid_json(bundle, name):
    payload = bundle[name]
    payload["version"] = "x" * 270000
    with pytest.raises(PolicyPackageError) as error:
        VALIDATORS[name](payload)
    assert error.value.code == "too_large"
    payload["version"] = float("nan")
    with pytest.raises(PolicyPackageError) as error:
        VALIDATORS[name](payload)
    assert error.value.code == "invalid_json"


@pytest.mark.parametrize("change,code", [
    (lambda b: b["profile"]["generation_limits"].update(max_sections=True), "invalid_limit"),
    (lambda b: b["profile"].update(coverage_mode="unknown"), "invalid_value"),
    (lambda b: b["coverage_plan"]["items"][0].update(requirement_ids=[]), "missing_requirement"),
    (lambda b: b["coverage_plan"]["items"][0].update(disposition="undetermined"), "missing_review"),
    (lambda b: b["package"]["requirements"][0].update(evidence_ids=[]), "missing_evidence"),
    (lambda b: b["package"]["requirements"][0].update(owner=""), "invalid_value"),
    (lambda b: b["package"]["evidence"][0].update(corpus_status="unverified"), "invalid_value"),
    (lambda b: b["package"]["errors"].append({"code": "secret", "stage": "generation", "reference_id": None}), "invalid_value"),
    (lambda b: b["package"]["exclusions"].append({"kind": "free_text", "target_id": "x", "reason": "x"}), "invalid_value"),
    (lambda b: b["package"]["sections"][0].update(extra="x"), "unknown_field"),
    (lambda b: b["budget_quote"].update(estimated_amount="1e6"), "invalid_amount"),
    (lambda b: b["budget_quote"].update(max_calls=True), "invalid_limit"),
    (lambda b: b["budget_quote"].update(reason_code="unknown_price"), "invalid_value"),
    (lambda b: b["budget_quote"].update(reserved_upper_bound="0.01"), "invalid_rounding"),
])
def test_invalid_local_shape_fails_closed(bundle, change, code):
    change(bundle)
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == code


@pytest.mark.parametrize("change,code", [
    (lambda b: b["package"].update(profile_id="profile-other"), "binding_mismatch"),
    (lambda b: b["budget_quote"].update(coverage_plan_id="plan-other"), "binding_mismatch"),
    (lambda b: b["package"]["requirements"][0].update(coverage_id="cov-other"), "coverage_mismatch"),
    (lambda b: b["package"]["requirements"][0].update(obligation="optional"), "coverage_mismatch"),
    (lambda b: b["package"]["evidence"][0].update(source_unit_id="unit-other"), "unplanned_evidence"),
    (lambda b: b["package"]["provenance"].update(source_inventory_hash="e" * 64), "binding_mismatch"),
    (lambda b: b["package"]["sections"][0].update(requirement_ids=[]), "missing_reference"),
    (lambda b: b["package"]["actions"][0].update(requirement_id="req-other"), "unknown_reference"),
    (lambda b: b["profile"]["generation_limits"].update(max_sections=1), None),
])
def test_cross_contract_or_graph_mismatch_fails_closed(bundle, change, code):
    change(bundle)
    if code is None:
        bundle["package"]["sections"].append({
            "id": "sec-synthetic-002", "title": "Extra", "body": "Extra section", "requirement_ids": [],
        })
        code = "too_large"
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == code


def test_blocked_quote_can_explain_insufficient_budget(bundle):
    quote = bundle["budget_quote"]
    quote.update(estimated_amount="0.020000", unrounded_upper_bound="0.020001",
                 reserved_upper_bound="0.03", run_cap="0.00",
                 status="blocked", reason_code="insufficient_budget")
    assert check_bundle(bundle)[3]["status"] == "blocked"


def _add_pending_unit(bundle, disposition):
    bundle["coverage_plan"]["items"].append({
        "id": "cov-synthetic-002", "source_unit_id": "unit-synthetic-002",
        "disposition": disposition, "obligation": "mandatory",
        "rationale": "A synthetic applicability question remains open.",
        "fact_refs": [], "rule_ids": ["rule-synthetic-002"],
        "evidence_ids": [], "requirement_ids": [],
        "review_disposition": "none", "gap_ids": [],
    })


@pytest.mark.parametrize("disposition", ["conditional", "undetermined"])
def test_pending_mandatory_unit_requires_linked_review_gap(bundle, disposition):
    _add_pending_unit(bundle, disposition)
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "missing_review"
    item = bundle["coverage_plan"]["items"][1]
    item.update(review_disposition="review_required", gap_ids=["gap-synthetic-002"])
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "unknown_reference"
    bundle["coverage_plan"]["unresolved_gaps"].append({
        "id": "gap-synthetic-002", "source_unit_id": "unit-synthetic-002",
        "reason": "Synthetic scope cannot yet be determined.", "review_owner": "Compliance expert",
    })
    assert check_bundle(bundle)[1]["items"][1]["review_disposition"] == "review_required"


def test_gap_must_be_linked_to_the_same_source_unit(bundle):
    _add_pending_unit(bundle, "undetermined")
    item = bundle["coverage_plan"]["items"][1]
    item.update(review_disposition="review_required", gap_ids=["gap-synthetic-002"])
    bundle["coverage_plan"]["unresolved_gaps"].append({
        "id": "gap-synthetic-002", "source_unit_id": "unit-synthetic-001",
        "reason": "Wrong unit", "review_owner": "Compliance expert",
    })
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "unlinked_gap"


def _add_extra_evidence(bundle, *, role="grounding", source_unit_id="unit-synthetic-002", candidate_reason=None):
    record = deepcopy(bundle["package"]["evidence"][0])
    record.update(id="ev-synthetic-002", source_unit_id=source_unit_id,
                  role=role, candidate_reason=candidate_reason)
    bundle["package"]["evidence"].append(record)


def test_unplanned_or_unreferenced_grounding_evidence_rejected(bundle):
    _add_extra_evidence(bundle)
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "unplanned_evidence"
    bundle["package"]["evidence"][1]["source_unit_id"] = "unit-synthetic-001"
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "unplanned_evidence"


def test_explicit_candidate_is_distinct_and_cannot_ground_requirement(bundle):
    _add_extra_evidence(bundle, role="candidate", candidate_reason="Awaiting rights and applicability review")
    assert len(check_bundle(bundle)[2]["evidence"]) == 2
    bundle["package"]["requirements"][0]["evidence_ids"].append("ev-synthetic-002")
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "candidate_used_as_grounding"


def test_candidate_requires_reason_and_unplanned_source_unit(bundle):
    _add_extra_evidence(bundle, role="candidate")
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "invalid_value"
    bundle["package"]["evidence"][1].update(candidate_reason="Review first", source_unit_id="unit-synthetic-001")
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "candidate_used_as_grounding"


def test_empty_actions_require_explicit_reason_per_requirement(bundle):
    bundle["package"]["actions"] = []
    bundle["package"]["requirements"][0]["action_ids"] = []
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "invalid_value"
    bundle["package"]["requirements"][0]["no_action_reason"] = "Existing control already implements this requirement."
    assert check_bundle(bundle)[2]["actions"] == []


def test_action_and_no_action_reason_are_mutually_exclusive(bundle):
    bundle["package"]["requirements"][0]["no_action_reason"] = "No action"
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "conflicting_action"


@pytest.mark.parametrize("raw,reserved", [
    ("0.000001", "0.01"),
    ("0.010001", "0.02"),
    ("0.020000", "0.02"),
])
def test_subcent_quote_rounds_upper_bound_up(bundle, raw, reserved):
    quote = bundle["budget_quote"]
    quote.update(estimated_amount=raw, unrounded_upper_bound=raw,
                 reserved_upper_bound=reserved, run_cap="0.02")
    assert check_bundle(bundle)[3]["reserved_upper_bound"] == reserved
    quote["reserved_upper_bound"] = f"{max(0, int(100 * float(reserved)) - 1) / 100:.2f}"
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "invalid_rounding"


def test_quote_rejects_understated_raw_upper_bound(bundle):
    bundle["budget_quote"].update(estimated_amount="0.000002", unrounded_upper_bound="0.000001",
                                  reserved_upper_bound="0.01", run_cap="0.01")
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "invalid_budget_order"


def test_section_cannot_claim_another_sections_requirement(bundle):
    bundle["package"]["sections"].append({
        "id": "sec-synthetic-002", "title": "Other", "body": "Other synthetic section",
        "requirement_ids": ["req-synthetic-001"],
    })
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "conflicting_reference"


def test_unknown_key_is_not_exposed_in_error(bundle):
    bundle["package"]["secret-key-material"] = "secret-value"
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(bundle)
    assert error.value.code == "unknown_field"
    assert "secret-key-material" not in str(error.value)


def test_validator_can_assess_structure_without_markdown(bundle):
    package = bundle["package"]
    package["sections"][0]["body"] = "No Markdown requirement marker or citation here."
    profile, plan, checked_package, quote = check_bundle(bundle)
    mandatory_ids = {
        requirement["id"] for requirement in checked_package["requirements"]
        if requirement["obligation"] == "mandatory"
    }
    assert mandatory_ids == {"req-synthetic-001"}
    assert plan["items"][0]["requirement_ids"] == sorted(mandatory_ids)
    assert checked_package["requirements"][0]["evidence_ids"] == ["ev-synthetic-001"]
    assert checked_package["actions"][0]["requirement_id"] in mandatory_ids
    assert profile["document_profile"] == "standard"
    assert quote["status"] == "estimate_only"


def test_error_does_not_echo_sensitive_payload(bundle):
    payload = deepcopy(bundle)
    payload["package"]["errors"][0:0] = [{
        "code": "generation_failed", "stage": "generation",
        "reference_id": "secret-value-not-in-error",
    }]
    payload["package"]["errors"][0]["code"] = "provider-exception-secret-value-not-in-error"
    with pytest.raises(PolicyPackageError) as error:
        check_bundle(payload)
    assert "secret-value-not-in-error" not in str(error.value)
    assert len(error.value.field) <= 160
