"""Context-bound validation, update chaining, and tenant-owned traces."""

from unittest.mock import MagicMock, patch

import pytest
from flask import g

from app import mongo
from app.agents.roles.coordinator import Coordinator
from app.services.logic import send_policy_update_to_policy_agent
from app.workload_token import VerifierKey, mint_token, verify_token
from workload_test_keys import KEY_IDS, signing_key


CONTEXT_A = "6825a0e00194d322881db128"
CONTEXT_B = "6825a0e00194d322881db129"


def _headers(context_id=CONTEXT_A, tenant_id="tenant-a"):
    token = mint_token(
        key=signing_key("context-agent"), kid=KEY_IDS["context-agent"],
        subject="context-agent", audience="validator-agent", scope="policy:validate",
        tenant_id=tenant_id, path="/validate-policy", context_id=context_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _principal(context_id=CONTEXT_A, tenant_id="tenant-a"):
    g.service_principal = {
        "authentication": "signed_workload_token", "identity": "context-agent",
        "audience": "validator-agent", "scopes": ["policy:validate"],
        "tenant_id": tenant_id, "context_id": context_id,
    }


def _send(context_id):
    return send_policy_update_to_policy_agent(
        context_id=context_id, language="en", policy_text="Synthetic draft",
        policy_agent_version="mock", generated_at="2026-01-01T00:00:00Z",
        status="review", reasons=["Synthetic gap"], recommendations=["Synthetic fix"],
    )


def test_validator_rejects_body_context_mismatch_before_pipeline(client):
    with patch("app.routes.routes.run_validation_pipeline") as pipeline:
        response = client.post(
            "/validate-policy", json={"context_id": CONTEXT_B}, headers=_headers(),
        )
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "service_context_forbidden"
    pipeline.assert_not_called()


def test_validator_body_mismatch_does_not_consume_token(client):
    headers = _headers()
    with patch("app.routes.routes.run_validation_pipeline", return_value={
        "context_id": CONTEXT_A, "policy_text": "Synthetic policy",
    }) as pipeline:
        mismatch = client.post("/validate-policy", json={"context_id": CONTEXT_B}, headers=headers)
        corrected = client.post("/validate-policy", json={"context_id": CONTEXT_A}, headers=headers)
        replay = client.post("/validate-policy", json={"context_id": CONTEXT_A}, headers=headers)
    assert mismatch.status_code == 403
    assert corrected.status_code == 200
    assert replay.status_code == 401
    pipeline.assert_called_once()


def test_validator_binds_verified_context_and_tenant_to_policy_update(app):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"context_id": CONTEXT_A, "policy_text": "Revised synthetic policy"}
    with app.test_request_context("/validate-policy", method="POST"):
        _principal()
        with patch("app.services.logic.requests.post", return_value=response) as post:
            result = _send(CONTEXT_A)
    assert result["context_id"] == CONTEXT_A
    path = f"/generate_policy/{CONTEXT_A}/update"
    assert post.call_args.args == (f"http://policy-agent:5000{path}",)
    assert post.call_args.kwargs["json"]["context_id"] == CONTEXT_A
    token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    claims = verify_token(
        token,
        caller_keys={app.config["WORKLOAD_VALIDATOR_SIGNING_KID"]: VerifierKey(
            "validator-agent", app.config["WORKLOAD_VALIDATOR_SIGNING_KEY"].public_key(),
            frozenset({"tenant-a"}), None,
        )},
        allowed_scopes={"validator-agent": frozenset({"policy:update"})},
        audience="policy-agent", scope="policy:update", method="POST", path=path,
    )
    assert claims["context_id"] == CONTEXT_A
    assert claims["tenant_id"] == "tenant-a"
    assert claims["version"] == 2


def test_validator_never_sends_update_for_another_context(app):
    with app.test_request_context("/validate-policy", method="POST"):
        _principal()
        with patch("app.services.logic.requests.post") as post:
            result = _send(CONTEXT_B)
    assert result["error_code"] == "workload_identity_unavailable"
    post.assert_not_called()


def test_validator_rejects_unbound_policy_update_response():
    coordinator = Coordinator.__new__(Coordinator)
    with pytest.raises(RuntimeError, match="mismatched context_id"):
        coordinator.validate_policy_update_response(
            {"policy_text": "Revised synthetic policy"}, CONTEXT_A,
        )


def test_validation_record_tenant_is_from_verified_principal(app):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.validation = {"rounds": 1, "consensus_threshold": 1, "vote_strategy": "majority"}
    results = [{"role": "AWC", "status": "accepted", "text": "Synthetic policy"}]
    with app.test_request_context("/validate-policy", method="POST"):
        _principal(tenant_id="tenant-a")
        coordinator.log_validation(CONTEXT_A, results, "accepted", 1, True)
        _principal(tenant_id="another-organization")
        coordinator.log_validation(CONTEXT_A, results, "accepted", 1, True)
    assert mongo.db.validations.count_documents({"organization_id": "tenant-a", "context_id": CONTEXT_A}) == 1
    assert mongo.db.validations.count_documents({"organization_id": "another-organization", "context_id": CONTEXT_A}) == 1


def test_validation_record_requires_verified_context_and_get_stays_closed(app, client):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.validation = {"rounds": 1, "consensus_threshold": 1, "vote_strategy": "majority"}
    with app.test_request_context("/validate-policy", method="POST"):
        _principal(context_id=CONTEXT_A)
        with pytest.raises(ValueError, match="Verified validation context"):
            coordinator.log_validation(CONTEXT_B, [], "review", 1, False)
    assert mongo.db.validations.count_documents({}) == 0
    response = client.get(f"/validation/{CONTEXT_A}")
    assert response.status_code == 404
    assert response.get_json()["error_code"] == "validation_read_unavailable"
