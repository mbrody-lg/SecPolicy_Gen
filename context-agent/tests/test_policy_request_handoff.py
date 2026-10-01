"""Approved 1.1 handoff stays bound to the current Context snapshot."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from bson import ObjectId
from flask import g

from app import mongo
from app.services import logic
from app.context_analysis.policy_input import build_approved_request
from app.workload_token import VerifierKey, verify_token
from test_policy_input import EXAMPLES, context_with_answers, example_answers, structured_answers, synthetic_handoff


TENANT = "test-organization"


def _approved_context():
    handoff = synthetic_handoff()
    context = context_with_answers(structured_answers(example_answers(EXAMPLES[0])))
    context["_id"] = ObjectId()
    context["organization_id"] = TENANT
    context["status"] = "context_ready_for_policy"
    context["refined_prompt"] = "Synthetic approved prompt"
    context["language"] = "es"
    request = build_approved_request(context, handoff, tenant_id=TENANT)
    context["policy_input"]["approval"] = {
        "revision": 1, "request": deepcopy(request),
        "answer_snapshot": deepcopy(context["policy_input"]["answers"]),
    }
    mongo.db.contexts.insert_one(context)
    return context, handoff, request


def test_context_emits_full_approved_request_and_signed_snapshot(app, monkeypatch):
    context, handoff, request = _approved_context()
    monkeypatch.setattr(logic, "policy_handoff_context_from_context_record", lambda _context: deepcopy(handoff))
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"context_id": str(context["_id"]), "policy_text": "Synthetic policy"}

    def post(_url, *, json, headers, timeout):
        captured.update(body=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(logic.requests, "post", post)
    with app.test_request_context("/"):
        g.organization_id = TENANT
        payload = logic.get_context_and_prompt(str(context["_id"]))
        assert payload["policy_request"] == request
        assert payload["language"] == request["policy_intent"]["language"]["value"]
        assert "business_context" not in payload
        assert "generated_at" not in payload
        logic.call_policy_agent(payload)

    assert captured["body"]["policy_request"] == request
    credential = captured["headers"]["Authorization"].removeprefix("Bearer ")
    claims = verify_token(
        credential,
        caller_keys={app.config["WORKLOAD_CONTEXT_SIGNING_KID"]: VerifierKey(
            "context-agent", app.config["WORKLOAD_CONTEXT_SIGNING_KEY"].public_key(),
            frozenset({TENANT}), None,
        )},
        allowed_scopes={"context-agent": frozenset({"policy:generate"})},
        audience="policy-agent", scope="policy:generate", method="POST", path="/generate_policy",
    )
    assert claims["snapshot_hash"] == request["approved_context"]["snapshot_hash"]
    assert claims["plan_revision_id"] == request["approved_context"]["plan_revision_id"]


def test_revoked_approval_before_signing_causes_zero_outbound_calls(app, monkeypatch):
    context, handoff, _request = _approved_context()
    monkeypatch.setattr(logic, "policy_handoff_context_from_context_record", lambda _context: deepcopy(handoff))
    with app.test_request_context("/"):
        g.organization_id = TENANT
        payload = logic.get_context_and_prompt(str(context["_id"]))
        mongo.db.contexts.update_one(
            {"_id": context["_id"]}, {"$set": {"policy_input.approval": None}},
        )
        with patch.object(logic.requests, "post") as post:
            with pytest.raises(logic.PipelineStepError) as error:
                logic.call_policy_agent(payload)
        assert error.value.error_code == "policy_input_not_approved"
        post.assert_not_called()


def test_approved_context_cannot_use_legacy_unsigned_generation(app, monkeypatch):
    context, _handoff, _request = _approved_context()
    with app.test_request_context("/"):
        g.organization_id = TENANT
        with patch.object(logic.requests, "post") as post:
            with pytest.raises(logic.PipelineStepError) as error:
                logic.call_policy_agent({"context_id": str(context["_id"]),
                                         "refined_prompt": "synthetic legacy bypass"})
        assert error.value.error_code == "policy_input_not_approved"
        post.assert_not_called()
