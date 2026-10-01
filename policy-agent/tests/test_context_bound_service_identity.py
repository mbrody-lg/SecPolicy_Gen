"""Negative context-bound service identity checks at Policy ingress."""

from unittest.mock import patch

import jwt
import pytest

from app.workload_token import InvalidWorkloadToken, mint_token, verify_token
from workload_test_keys import KEY_IDS, signing_key


CONTEXT_A = "6825a0e00194d322881db128"
CONTEXT_B = "6825a0e00194d322881db129"


def _headers(path, scope, context_id=CONTEXT_A, subject="context-agent"):
    token = mint_token(
        key=signing_key(subject), kid=KEY_IDS[subject], subject=subject,
        audience="policy-agent", scope=scope, tenant_id="tenant-a", path=path,
        context_id=context_id,
    )
    return {"Authorization": f"Bearer {token}"}


def test_generate_body_mismatch_rejected_before_pipeline(client):
    with patch("app.routes.routes.run_generation_pipeline") as pipeline:
        response = client.post(
            "/generate_policy", json={"context_id": CONTEXT_B},
            headers=_headers("/generate_policy", "policy:generate"),
        )
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "service_context_forbidden"
    pipeline.assert_not_called()


def test_generate_body_mismatch_does_not_consume_token(client):
    headers = _headers("/generate_policy", "policy:generate")
    with patch("app.routes.routes.run_generation_pipeline", return_value={
        "success": True, "policy": {"context_id": CONTEXT_A, "policy_text": "Synthetic policy"},
    }) as pipeline:
        mismatch = client.post("/generate_policy", json={"context_id": CONTEXT_B}, headers=headers)
        corrected = client.post("/generate_policy", json={"context_id": CONTEXT_A}, headers=headers)
        replay = client.post("/generate_policy", json={"context_id": CONTEXT_A}, headers=headers)
    assert mismatch.status_code == 403
    assert corrected.status_code == 200
    assert replay.status_code == 401
    pipeline.assert_called_once()


def test_update_body_mismatch_does_not_consume_token(client):
    path = f"/generate_policy/{CONTEXT_A}/update"
    headers = _headers(path, "policy:update", subject="validator-agent")
    with patch("app.routes.routes.run_policy_update_pipeline", return_value={
        "success": True, "policy": {"context_id": CONTEXT_A, "policy_text": "Synthetic policy"},
    }) as pipeline:
        mismatch = client.post(path, json={"context_id": CONTEXT_B}, headers=headers)
        corrected = client.post(path, json={"context_id": CONTEXT_A}, headers=headers)
        replay = client.post(path, json={"context_id": CONTEXT_A}, headers=headers)
    assert mismatch.status_code == 403
    assert corrected.status_code == 200
    assert replay.status_code == 401
    pipeline.assert_called_once()


def test_matching_v2_generation_is_one_use(client):
    headers = _headers("/generate_policy", "policy:generate")
    with patch("app.routes.routes.run_generation_pipeline", return_value={
        "success": True, "policy": {"context_id": CONTEXT_A, "policy_text": "Synthetic policy"},
    }) as pipeline:
        first = client.post("/generate_policy", json={"context_id": CONTEXT_A}, headers=headers)
        replay = client.post("/generate_policy", json={"context_id": CONTEXT_A}, headers=headers)
    assert first.status_code == 200
    assert replay.status_code == 401
    pipeline.assert_called_once()


def test_update_path_and_body_must_both_match_token(client):
    path = f"/generate_policy/{CONTEXT_B}/update"
    with patch("app.routes.routes.run_policy_update_pipeline") as pipeline:
        response = client.post(
            path, json={"context_id": CONTEXT_A},
            headers=_headers(path, "policy:update", subject="validator-agent"),
        )
    assert response.status_code == 403
    pipeline.assert_not_called()

    path = f"/generate_policy/{CONTEXT_A}/update"
    with patch("app.routes.routes.run_policy_update_pipeline") as pipeline:
        response = client.post(
            path, json={"context_id": CONTEXT_B},
            headers=_headers(path, "policy:update", subject="validator-agent"),
        )
    assert response.status_code == 403
    pipeline.assert_not_called()


def test_v1_token_cannot_downgrade_generation(app):
    v2 = _headers("/generate_policy", "policy:generate")["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(v2, options={"verify_signature": False})
    claims.pop("context_id")
    claims["version"] = 1
    v1 = jwt.encode(
        claims, signing_key("context-agent"), algorithm="EdDSA",
        headers={"kid": KEY_IDS["context-agent"], "typ": "secpolicy-workload-v1"},
    )
    with pytest.raises(InvalidWorkloadToken):
        verify_token(
            v1, caller_keys=app.config["WORKLOAD_CALLER_KEYS"],
            allowed_scopes={"context-agent": frozenset({"policy:generate"})},
            audience="policy-agent", scope="policy:generate", method="POST",
            path="/generate_policy",
        )


def test_candidate_capability_remains_v1(app):
    token = mint_token(
        key=signing_key("docker-agent"), kid=KEY_IDS["docker-agent"],
        subject="docker-agent", audience="policy-agent",
        scope="policy:candidate:generate", tenant_id="tenant-a",
        path="/candidate/generate-policy",
    )
    assert jwt.get_unverified_header(token)["typ"] == "secpolicy-workload-v1"
    claims = verify_token(
        token, caller_keys=app.config["WORKLOAD_CALLER_KEYS"],
        allowed_scopes={"docker-agent": frozenset({"policy:candidate:generate"})},
        audience="policy-agent", scope="policy:candidate:generate",
        method="POST", path="/candidate/generate-policy",
    )
    assert claims["version"] == 1
    assert "context_id" not in claims
