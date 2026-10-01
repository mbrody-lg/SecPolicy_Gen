"""Synthetic canonical ingress checks; no external model or corpus is used."""

from unittest.mock import patch

import pytest

from contracts.policy_request_v1 import compute_policy_input_hash_v1_1
from app.rag.context import build_retrieval_context
from app.rag.planner import build_retrieval_plan
from app.services.logic import run_generation_pipeline, validate_generation_payload


def _decision(value, *, source="provided"):
    return {"value": value, "source": source, "source_ref": "synthetic:revision:1",
            "confidence": "confirmed"}


def _request():
    scope = {field: _decision(value) for field, value in {
        "legal_entities": ["Example Ltd"], "size_band": "small",
        "jurisdictions": ["Spain"], "sectors": ["Healthcare"],
        "services": ["Care"], "data_categories": ["health_data"],
    }.items()}
    handoff = {
        "contract": "context_agent.policy_handoff", "version": "1.0", "source": "context-agent",
        "plan_revision_id": "revision-1", "context_snapshot_hash": "a" * 64,
        "security_context_version": "1.0", "final_context_version": "1.0",
        "final_context_status": "ready", "context_ready_for_policy": True,
        "final_context_sections": {"scope": {"status": "accepted", "content": "Synthetic scope"}},
        "structured_findings": [{"status": "completed", "task_id": "synthetic-task",
                                 "findings": ["Synthetic risk"]}],
        "retrieval_hints": {"collection_families": ["legal_norms"]},
        "unresolved_gaps": [],
    }
    intent = {field: _decision(value) for field, value in {
        "policy_type": "Information security", "scope": "Care systems",
        "audience": ["Staff"], "exclusions": [], "requested_instruments": [],
        "document_profile": "standard", "coverage_mode": "risk_based", "language": "en",
    }.items()}
    facts = {field: _decision(value) for field, value in {
        "current_posture": "Basic controls", "target_posture": "Managed controls",
        "maturity": "Initial", "risk_appetite": "Low", "risk_tolerance": "Low",
        "existing_controls": ["Backups"], "known_gaps": ["Review access"],
        "constraints": ["Small team"], "governance_owner": "CISO",
        "business_priorities": ["Patient safety"], "critical_processes": ["Care delivery"],
    }.items()}
    facts["entity_scope"] = scope
    request = {
        "contract": "secpolicy.policy_request", "version": "1.1", "context_id": "context-1",
        "approved_context": {
            "approval_status": "approved", "context_id": "context-1", "tenant_id": "tenant-a",
            "plan_revision_id": "revision-1", "snapshot_hash": "0" * 64,
            "legacy_handoff_hash": "a" * 64, "hash_scope": "policy_input_v1_1",
            "policy_handoff_context": handoff,
        },
        "policy_intent": intent, "business_facts": facts,
        "origin": {"contract": handoff["contract"], "version": handoff["version"], "defaults": {}},
    }
    request["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1_1(request)
    return request


def _payload(request=None):
    return {"context_id": "context-1", "refined_prompt": "Draft a policy.",
            "language": "en", "model_version": "mock", "policy_request": request or _request()}


def test_full_request_survives_normalization_and_retrieval(app_context):
    request = _request()
    normalized = validate_generation_payload(_payload(request), organization_id="tenant-a")
    context = build_retrieval_context(normalized)
    plan = build_retrieval_plan(context, {"version": "1.0", "sources": []})
    assert normalized["policy_request"] == request
    assert context.policy_request == request
    assert plan.policy_request == request
    assert context.policy_request is normalized["policy_request"]
    assert plan.policy_request is normalized["policy_request"]
    assert context.critical_assets == ["Care delivery"]
    request["business_facts"]["critical_processes"]["value"].append("Tampered")
    assert plan.policy_request != request


@pytest.mark.parametrize("change", [
    lambda p: p["policy_request"].pop("business_facts"),
    lambda p: p["policy_request"]["business_facts"]["critical_processes"].update(value=None),
    lambda p: p.update(language="fr"),
    lambda p: p.update(business_context={"country": "Spain"}),
    lambda p: p.update(unknown_transport="drop me"),
    lambda p: p["policy_request"]["approved_context"].update(tenant_id="tenant-b"),
])
def test_invalid_canonical_input_fails_before_provider_or_write(app_context, change):
    payload = _payload()
    change(payload)
    with patch("app.services.logic.run_with_agent") as agent, patch("app.services.logic.mongo.db") as db:
        result = run_generation_pipeline(payload, organization_id="tenant-a")
    assert result["status_code"] in (400, 403)
    agent.assert_not_called()
    db.policies.find_one.assert_not_called()
    db.policies.insert_one.assert_not_called()


@pytest.mark.parametrize("path", [
    *( ("policy_intent", field) for field in (
        "policy_type", "scope", "audience", "exclusions", "requested_instruments",
        "document_profile", "coverage_mode", "language",
    )),
    *( ("business_facts", field) for field in (
        "current_posture", "target_posture", "maturity", "risk_appetite",
        "risk_tolerance", "existing_controls", "known_gaps", "constraints",
        "governance_owner", "business_priorities", "critical_processes",
    )),
    *( ("business_facts", "entity_scope", field) for field in (
        "legal_entities", "size_band", "jurisdictions", "sectors", "services",
        "data_categories",
    )),
    *( ("approved_context", "policy_handoff_context", field) for field in (
        "final_context_sections", "structured_findings", "retrieval_hints",
        "unresolved_gaps",
    )),
])
def test_deleting_each_critical_fact_fails_even_with_recomputed_hash(app_context, path):
    request = _request()
    node = request
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    request["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1_1(request)
    with patch("app.services.logic.run_with_agent") as agent, patch("app.services.logic.mongo.db") as db:
        result = run_generation_pipeline(_payload(request), organization_id="tenant-a")
    assert result["success"] is False
    assert result["status_code"] == 400
    agent.assert_not_called()
    db.policies.find_one.assert_not_called()
    db.policies.insert_one.assert_not_called()


def test_canonical_prompt_contains_full_request_and_plan(app_context):
    from app.services import logic

    request = _request()
    captured = {}

    class FakeAgent:
        def run(self, *, prompt, context_id, retrieval_plan):
            captured.update(prompt=prompt, context_id=context_id, plan=retrieval_plan)
            return {"text": "Synthetic policy"}

    with patch.object(logic, "load_policy_config", return_value={}), \
            patch.object(logic, "create_agent_from_config", return_value=FakeAgent()), \
            patch.object(logic, "load_rag_source_manifest", return_value={"version": "1.0", "sources": []}), \
            patch.object(logic, "_validate_agent_result", side_effect=lambda result, _config: result):
        logic.run_with_agent("Draft a policy.", "context-1", "mock", policy_request=request)
    assert '"business_priorities"' in captured["prompt"]
    assert '"retrieval_hints"' in captured["prompt"]
    assert captured["plan"].policy_request == request


def test_unknown_canonical_field_is_not_reflected(app_context):
    request = _request()
    secret_field = "private-secret-do-not-reflect"
    request["business_facts"][secret_field] = _decision("synthetic")
    with patch("app.services.logic.run_with_agent") as agent:
        result = run_generation_pipeline(_payload(request), organization_id="tenant-a")
    assert result["success"] is False
    assert secret_field not in str(result)
    agent.assert_not_called()


def test_approved_request_over_prompt_budget_fails_before_provider_or_write(app_context):
    request = _request()
    values = [f"synthetic-{index}-" + ("x" * 390) for index in range(24)]
    for field in ("existing_controls", "known_gaps"):
        request["business_facts"][field]["value"] = values
    request["approved_context"]["snapshot_hash"] = compute_policy_input_hash_v1_1(request)
    with patch("app.services.logic.run_with_agent") as agent, patch("app.services.logic.mongo.db") as db:
        result = run_generation_pipeline(_payload(request), organization_id="tenant-a")
    assert result["success"] is False
    assert result["error_code"] == "too_large"
    agent.assert_not_called()
    db.policies.find_one.assert_not_called()
    db.policies.insert_one.assert_not_called()
