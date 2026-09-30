"""Synthetic W02 projection, material-gate, and approval-binding tests."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from app.context_analysis.policy_input import (
    PolicyInputError,
    approved_request_is_current,
    build_approved_request,
    material_questions,
    validate_answer_patch,
)

CONTEXT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((CONTEXT_ROOT / "app/config/examples/answers").glob("*.yaml"))
TENANT = "synthetic-tenant-001"


def synthetic_handoff(country="Spain", sector="Education and language training"):
    return {
        "contract": "context_agent.policy_handoff", "version": "1.0", "source": "context-agent",
        "security_context_version": "1.0", "final_context_version": "1.0",
        "plan_revision_id": "synthetic-plan-001", "context_snapshot_hash": "a" * 64,
        "business_context": {"country": country, "sector": sector, "data_types": []},
        "final_context_status": "ready", "context_ready_for_policy": True,
        "final_context_sections": {"profile": {"status": "accepted", "content": "Synthetic profile"}},
        "structured_findings": [{"status": "completed", "task_id": "synthetic-task-001",
                                 "findings": ["Synthetic control gap"]}],
        "retrieval_hints": {"collection_families": ["synthetic-controls"]},
        "unresolved_gaps": [],
    }


def answer(value, confidence="confirmed"):
    return {"value": value, "confidence": confidence}


def example_answers(path):
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {entry["id"]: entry["answer"] for entry in payload["answers"]}


def structured_answers(example):
    return {
        "policy_intent.policy_type": answer(example["policy_type"]),
        "policy_intent.scope": answer(example["policy_scope"]),
        "policy_intent.audience": answer([item.strip() for item in example["policy_audience"].split(",")]),
        "policy_intent.exclusions": answer([]),
        "policy_intent.document_profile": answer("standard"),
        "policy_intent.coverage_mode": answer("risk_based"),
        "policy_intent.language": answer("en"),
        "business_facts.entity_scope.legal_entities": answer(["Synthetic Example Ltd"]),
        "business_facts.entity_scope.jurisdictions": answer([example["country"]]),
        "business_facts.entity_scope.sectors": answer([example["sector"]]),
        "business_facts.entity_scope.services": answer([example["company_activity"][:500]]),
        "business_facts.business_priorities": answer([example["need"][:500]]),
        "business_facts.critical_processes": answer([example["critical_assets"][:500]]),
        "business_facts.current_posture": answer(example["current_security_operations"][:2000]),
    }


def context_with_answers(answers):
    validated = validate_answer_patch(answers)
    return {
        "_id": "synthetic-context-001", "organization_id": TENANT,
        "context_intelligence_plan": {
            "status": "approved", "approved_revision_id": "synthetic-plan-001",
        },
        "policy_input": {
            "version": "1.1", "revision": 1, "answers": validated,
            "revisions": [{"revision": 1, "answers": deepcopy(validated), "recorded_by": "synthetic-reviewer"}],
            "approval": None,
        },
    }


@pytest.fixture
def handoff():
    return synthetic_handoff()


@pytest.mark.parametrize("fixture_path", EXAMPLES, ids=lambda path: path.stem)
def test_ten_synthetic_organizations_project_to_valid_v1_1(fixture_path, handoff):
    example = example_answers(fixture_path)
    answers = structured_answers(example)
    context = context_with_answers(answers)
    assert material_questions(answers) == []
    request = build_approved_request(
        context, synthetic_handoff(example["country"], example["sector"]), tenant_id=TENANT,
    )
    assert request["version"] == "1.1"
    assert request["approved_context"]["hash_scope"] == "policy_input_v1_1"
    assert request["business_facts"]["business_priorities"]["source"] == "provided"
    assert request["business_facts"]["entity_scope"]["jurisdictions"]["source_ref"].endswith("@revision:1")
    assert request["policy_intent"]["requested_instruments"]["source"] == "unknown"


def test_missing_and_qualified_material_facts_ask_only_material_questions(handoff):
    answers = structured_answers(example_answers(EXAMPLES[0]))
    answers.pop("business_facts.business_priorities")
    answers["policy_intent.scope"]["confidence"] = "qualified"
    fields = {question["field"] for question in material_questions(answers)}
    assert fields == {"business_facts.business_priorities", "policy_intent.scope"}
    context = context_with_answers(answers)
    with pytest.raises(PolicyInputError, match="material_questions_open"):
        build_approved_request(context, handoff, tenant_id=TENANT)


def test_full_instrument_requires_explicit_instrument_and_territory(handoff):
    answers = structured_answers(example_answers(EXAMPLES[0]))
    answers["policy_intent.coverage_mode"] = answer("full_instrument")
    answers["business_facts.entity_scope.jurisdictions"] = answer([])
    fields = {question["field"] for question in material_questions(answers)}
    assert "policy_intent.requested_instruments" in fields
    assert "business_facts.entity_scope.jurisdictions" in fields
    with pytest.raises(PolicyInputError, match="invalid_instrument"):
        validate_answer_patch({"policy_intent.requested_instruments": answer([{"id": "example"}])})
    answers["policy_intent.requested_instruments"] = answer([{"id": "synthetic-instrument", "version": "fixture-1"}])
    answers["business_facts.entity_scope.jurisdictions"] = answer(["Exampleland"])
    answers["business_facts.entity_scope.data_categories"] = answer(["Synthetic records"])
    assert build_approved_request(
        context_with_answers(answers), synthetic_handoff(country="Exampleland"), tenant_id=TENANT,
    )["policy_intent"]["coverage_mode"]["value"] == "full_instrument"


@pytest.mark.parametrize("field", [
    "business_facts.entity_scope.sectors",
    "business_facts.entity_scope.services",
    "business_facts.entity_scope.data_categories",
])
def test_full_instrument_requires_applicability_facts(field, handoff):
    answers = structured_answers(example_answers(EXAMPLES[0]))
    answers["policy_intent.coverage_mode"] = answer("full_instrument")
    answers["policy_intent.requested_instruments"] = answer([{"id": "synthetic", "version": "v1"}])
    answers["business_facts.entity_scope.data_categories"] = answer(["Synthetic records"])
    answers.pop(field)
    assert field in {item["field"] for item in material_questions(answers)}
    with pytest.raises(PolicyInputError, match="material_questions_open"):
        build_approved_request(context_with_answers(answers), handoff, tenant_id=TENANT)


@pytest.mark.parametrize(("source_field", "answer_field", "source_value"), [
    ("country", "business_facts.entity_scope.jurisdictions", "France"),
    ("sector", "business_facts.entity_scope.sectors", "Different sector"),
    ("data_types", "business_facts.entity_scope.data_categories", ["Other records"]),
])
def test_approved_context_conflict_blocks_approval(source_field, answer_field, source_value, handoff):
    answers = structured_answers(example_answers(EXAMPLES[0]))
    answers["business_facts.entity_scope.data_categories"] = answer(["Synthetic records"])
    handoff["business_context"][source_field] = source_value
    with pytest.raises(PolicyInputError) as exc_info:
        build_approved_request(context_with_answers(answers), handoff, tenant_id=TENANT)
    assert exc_info.value.code == "context_fact_conflict"
    assert exc_info.value.field == answer_field


def test_approval_requires_reconcilable_handoff_facts(handoff):
    answers = structured_answers(example_answers(EXAMPLES[0]))
    handoff.pop("business_context")
    with pytest.raises(PolicyInputError) as exc_info:
        build_approved_request(context_with_answers(answers), handoff, tenant_id=TENANT)
    assert exc_info.value.code == "handoff_facts_missing"


def test_typed_exclusion_conflict_blocks_approval(handoff):
    answers = structured_answers(example_answers(EXAMPLES[0]))
    answers["policy_intent.exclusions"] = answer(["jurisdiction:" + answers["business_facts.entity_scope.jurisdictions"]["value"][0]])
    assert material_questions(answers)[0]["reason"] == "contradictory_exclusion"
    with pytest.raises(PolicyInputError, match="material_questions_open"):
        build_approved_request(context_with_answers(answers), handoff, tenant_id=TENANT)
    with pytest.raises(PolicyInputError, match="untyped_exclusion"):
        validate_answer_patch({"policy_intent.exclusions": answer(["plain free text"] )})


def test_provenance_must_match_immutable_answer_revision(handoff):
    context = context_with_answers(structured_answers(example_answers(EXAMPLES[0])))
    context["policy_input"]["answers"]["policy_intent.scope"] = answer("Tampered scope")
    with pytest.raises(PolicyInputError, match="answer_provenance_missing"):
        build_approved_request(context, handoff, tenant_id=TENANT)


def test_unchanged_answer_keeps_its_original_revision(handoff):
    context = context_with_answers(structured_answers(example_answers(EXAMPLES[0])))
    state = context["policy_input"]
    changed = deepcopy(state["answers"])
    changed["policy_intent.scope"] = answer("Revised scope")
    state["revision"] = 2
    state["answers"] = changed
    state["revisions"].append({"revision": 2, "answers": deepcopy(changed), "recorded_by": "second-reviewer"})

    request = build_approved_request(context, handoff, tenant_id=TENANT)
    assert request["policy_intent"]["scope"]["source_ref"].endswith("@revision:2")
    assert request["business_facts"]["entity_scope"]["jurisdictions"]["source_ref"].endswith("@revision:1")


def test_full_hash_invalidation_for_answers_handoff_plan_and_tenant(handoff):
    context = context_with_answers(structured_answers(example_answers(EXAMPLES[0])))
    request = build_approved_request(context, handoff, tenant_id=TENANT)
    context["policy_input"]["approval"] = {
        "revision": 1, "request": request,
        "answer_snapshot": deepcopy(context["policy_input"]["answers"]),
    }
    assert approved_request_is_current(context, handoff, tenant_id=TENANT)
    changed = deepcopy(context)
    changed["policy_input"]["answers"]["business_facts.business_priorities"] = answer(["Different priority"])
    assert not approved_request_is_current(changed, handoff, tenant_id=TENANT)
    changed = deepcopy(handoff)
    changed["final_context_sections"]["profile"]["content"] = "Changed accepted context"
    assert not approved_request_is_current(context, changed, tenant_id=TENANT)
    changed = deepcopy(handoff)
    changed["business_context"]["country"] = "France"
    assert not approved_request_is_current(context, changed, tenant_id=TENANT)
    changed = deepcopy(context)
    changed["context_intelligence_plan"]["approved_revision_id"] = "different-plan"
    assert not approved_request_is_current(changed, handoff, tenant_id=TENANT)
    assert not approved_request_is_current(context, handoff, tenant_id="foreign-tenant")


@pytest.mark.parametrize("patch", [
    {"unexpected": answer("x")},
    {"policy_intent.audience": answer(["x"] * 33)},
    {"policy_intent.policy_type": {"value": "x", "confidence": "unknown"}},
    {"policy_intent.policy_type": {"value": "x", "confidence": []}},
    {"policy_intent.policy_type": {"value": "x", "confidence": {}}},
    {"policy_intent.exclusions": answer(["unknown:target"])},
])
def test_invalid_answers_fail_before_persistence(patch):
    with pytest.raises(PolicyInputError):
        validate_answer_patch(patch)
