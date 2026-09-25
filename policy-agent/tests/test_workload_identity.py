"""Negative workload-capability matrix for protected Policy routes."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from app import mongo
from app.workload_token import (
    ForbiddenWorkloadToken,
    InvalidWorkloadToken,
    WorkloadReplay,
    combine_verifier_keys,
    consume_token,
    initialize_replay_store,
    load_signing_key,
    load_verifier_keys,
    mint_token,
    verify_token,
)
from workload_test_keys import KEY_IDS, signing_key, verifier_registry


def _token(app, **claims):
    data = {
        "key": signing_key("context-agent"),
        "kid": KEY_IDS["context-agent"],
        "subject": "context-agent", "audience": "policy-agent",
        "scope": "policy:generate", "tenant_id": "tenant-a", "path": "/generate_policy",
    }
    data.update(claims)
    return mint_token(**data)


def _verify(app, token, **expected):
    data = {
        "caller_keys": app.config["WORKLOAD_CALLER_KEYS"] if app is not None else {},
        "allowed_scopes": {"context-agent": frozenset({"policy:generate", "policy:rag:refresh"})},
        "audience": "policy-agent", "scope": "policy:generate",
        "method": "POST", "path": "/generate_policy",
    }
    data.update(expected)
    return verify_token(token, **data)


@pytest.mark.parametrize("change,error", [
    ({"audience": "validator-agent"}, ForbiddenWorkloadToken),
    ({"scope": "policy:rag:refresh"}, ForbiddenWorkloadToken),
    ({"path": "/rag/refresh"}, InvalidWorkloadToken),
])
def test_wrong_capability_is_rejected(app, change, error):
    with pytest.raises(error):
        _verify(app, _token(app, **change))


def test_tamper_and_foreign_signer_are_rejected(app):
    token = _token(app)
    with pytest.raises(InvalidWorkloadToken):
        _verify(app, token + "tamper")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    foreign = _token(app, key=Ed25519PrivateKey.from_private_bytes(bytes([5]) * 32))
    with pytest.raises(InvalidWorkloadToken):
        _verify(app, foreign)


def test_validator_signer_cannot_impersonate_context_agent(app):
    forged_subject = _token(
        app, key=signing_key("validator-agent"), kid=KEY_IDS["validator-agent"],
    )
    forged_key_id = _token(
        app, key=signing_key("validator-agent"), kid=KEY_IDS["context-agent"],
    )
    with pytest.raises(InvalidWorkloadToken):
        _verify(app, forged_subject)
    with pytest.raises(InvalidWorkloadToken):
        _verify(app, forged_key_id)


def test_duplicate_public_key_cannot_be_assigned_to_two_callers(app):
    context = app.config["WORKLOAD_CALLER_KEYS"][KEY_IDS["context-agent"]]
    with pytest.raises(ValueError, match="distinct"):
        combine_verifier_keys(
            {"context-kid": context},
            {"validator-kid": replace(context, subject="validator-agent")},
        )


def test_public_fixture_keys_are_rejected_outside_test_mode():
    import base64

    test_seed = base64.b64encode(bytes([1]) * 32).decode("ascii")
    with pytest.raises(ValueError, match="test-only"):
        load_signing_key("TEST_SIGNING_KEY", test_seed)
    with pytest.raises(ValueError, match="test-only"):
        load_verifier_keys(
            "TEST_VERIFY_KEYS", verifier_registry("context-agent"),
            subject="context-agent",
        )
    assert load_signing_key("TEST_SIGNING_KEY", test_seed, testing=True)
    assert load_verifier_keys(
        "TEST_VERIFY_KEYS", verifier_registry("context-agent"),
        subject="context-agent", testing=True,
    )


def test_candidate_key_cannot_claim_another_tenant(app):
    token = _token(
        app, key=signing_key("docker-agent"), kid=KEY_IDS["docker-agent"],
        subject="docker-agent", scope="policy:candidate:generate",
        tenant_id="tenant-b", path="/candidate/generate-policy",
    )
    with pytest.raises(ForbiddenWorkloadToken):
        _verify(app, token, scope="policy:candidate:generate",
                path="/candidate/generate-policy",
                allowed_scopes={"docker-agent": frozenset({"policy:candidate:generate"})})


def test_previous_key_is_accepted_only_during_bounded_overlap():
    previous = json.loads(verifier_registry("context-agent"))
    previous[KEY_IDS["context-agent"]]["accept_until"] = 1030
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64

    next_key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
    previous["context-test-v2"] = {
        "public_key_b64": base64.b64encode(next_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )).decode("ascii"),
        "tenant_ids": ["tenant-a"],
    }
    with patch("app.workload_token.time.time", return_value=1000):
        keys = load_verifier_keys(
            "TEST_CONTEXT_KEYS", json.dumps(previous), subject="context-agent",
            testing=True,
        )
        token = _token(None)
    with patch("app.workload_token.time.time", return_value=1029):
        assert _verify(None, token, caller_keys=keys)["sub"] == "context-agent"
    with patch("app.workload_token.time.time", return_value=1031):
        with pytest.raises(InvalidWorkloadToken):
            _verify(None, token, caller_keys=keys)
    previous[KEY_IDS["context-agent"]]["accept_until"] = 1601
    with patch("app.workload_token.time.time", return_value=1000):
        with pytest.raises(ValueError, match="600 seconds"):
            load_verifier_keys(
                "TEST_CONTEXT_KEYS", json.dumps(previous),
                subject="context-agent", testing=True,
            )


def test_expired_capability_is_rejected(app):
    with patch("app.workload_token.time.time", return_value=1000):
        token = _token(app)
    with patch("app.workload_token.time.time", return_value=1061):
        with pytest.raises(InvalidWorkloadToken):
            _verify(app, token)


def test_capability_replay_is_rejected(app):
    token = _token(app)
    claims = _verify(app, token)
    with app.app_context():
        consume_token(mongo.db, token, claims)
        with pytest.raises(WorkloadReplay):
            consume_token(mongo.db, token, claims)


def test_replay_ttl_index_is_initialized_before_request(app):
    token = _token(app)
    claims = _verify(app, token)
    with app.app_context():
        collection = mongo.db.workload_nonces
        initialize_replay_store(mongo.db)
        assert collection.index_information()["expires_at_1"]["expireAfterSeconds"] == 0
        with patch.object(collection, "create_index", side_effect=AssertionError("per-request index")):
            consume_token(mongo.db, token, claims)


def test_wrong_tenant_header_has_no_generation_side_effect(client, workload_headers):
    headers = workload_headers("/generate_policy", tenant_id="tenant-a")
    headers["X-Tenant-ID"] = "tenant-b"
    with patch("app.routes.routes.run_generation_pipeline") as pipeline:
        response = client.post("/generate_policy", json={}, headers=headers)
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "service_tenant_forbidden"
    pipeline.assert_not_called()


def test_replayed_route_token_has_no_second_generation(client, workload_headers):
    headers = workload_headers("/generate_policy")
    with patch("app.routes.routes.run_generation_pipeline", return_value={"success": True, "policy": {}}) as pipeline:
        first = client.post("/generate_policy", json={}, headers=headers)
        second = client.post("/generate_policy", json={}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 401
    assert pipeline.call_count == 1
