"""Tenant ownership and context-bound outbound workload authority."""

from unittest.mock import patch

import pytest
from bson import ObjectId
from flask import g

from app import mongo
from app.services import logic
from app.workload_token import VerifierKey, verify_token


TENANT_A = "test-organization"
TENANT_B = "another-organization"


def _context(tenant):
    document = {"_id": ObjectId(), "organization_id": tenant, "status": "context_ready_for_policy"}
    mongo.db.contexts.insert_one(document)
    return str(document["_id"])


def test_context_signs_only_owned_context_with_v2(app):
    owned = _context(TENANT_A)
    foreign = _context(TENANT_B)
    with app.test_request_context("/"):
        g.organization_id = TENANT_A
        headers = logic._dependency_headers(
            None, audience="policy-agent", scope="policy:generate",
            path="/generate_policy", context_id=owned,
        )
        claims = verify_token(
            headers["Authorization"].removeprefix("Bearer "),
            caller_keys={app.config["WORKLOAD_CONTEXT_SIGNING_KID"]: VerifierKey(
                "context-agent", app.config["WORKLOAD_CONTEXT_SIGNING_KEY"].public_key(),
                frozenset({TENANT_A}), None,
            )},
            allowed_scopes={"context-agent": frozenset({"policy:generate"})},
            audience="policy-agent", scope="policy:generate", method="POST",
            path="/generate_policy",
        )
        assert claims["version"] == 2
        assert claims["context_id"] == owned
        assert claims["tenant_id"] == TENANT_A

        with pytest.raises(logic.PipelineStepError) as error:
            logic._dependency_headers(
                None, audience="policy-agent", scope="policy:generate",
                path="/generate_policy", context_id=foreign,
            )
        assert error.value.error_code == "context_not_found"


def test_foreign_context_cannot_be_read_or_sent_to_policy(app):
    foreign = _context(TENANT_B)
    with app.test_request_context("/"):
        g.organization_id = TENANT_A
        with pytest.raises(logic.PipelineStepError) as error:
            logic.get_context_and_prompt(foreign)
        assert error.value.error_code == "context_not_found"
        with patch("app.services.logic.requests.post") as post:
            with pytest.raises(logic.PipelineStepError) as error:
                logic.call_policy_agent({"context_id": foreign, "refined_prompt": "synthetic"})
        assert error.value.error_code == "context_not_found"
        post.assert_not_called()


def test_validated_snapshot_requires_same_owned_context(app):
    owned = _context(TENANT_A)
    foreign = _context(TENANT_B)
    payload = {
        "context_id": foreign, "policy_text": "Synthetic policy", "generated_at": "2026-01-01T00:00:00Z",
        "policy_agent_version": "mock", "language": "en",
    }
    with app.test_request_context("/"):
        g.organization_id = TENANT_A
        with pytest.raises(logic.PipelineStepError) as error:
            logic.store_validated_policy(foreign, payload)
        assert error.value.error_code == "context_not_found"
        with pytest.raises(logic.PipelineStepError) as error:
            logic.store_validated_policy(owned, payload)
        assert error.value.error_code == "validation_context_mismatch"
    assert mongo.db.interactions.count_documents({}) == 0


def test_foreign_policy_response_is_not_sent_to_validator(app):
    owned = _context(TENANT_A)
    foreign = _context(TENANT_B)
    with app.test_request_context("/"):
        g.organization_id = TENANT_A
        with patch("app.services.logic.trigger_policy_generation", return_value={
            "success": True, "policy_data": {"context_id": foreign},
        }), patch("app.services.logic.call_validator_agent") as validator:
            result = logic.generate_full_policy_pipeline(owned)
    assert result["error_code"] == "policy_context_mismatch"
    validator.assert_not_called()
