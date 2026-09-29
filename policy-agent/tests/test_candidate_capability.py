from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import g

from app import mongo
from app.candidate_contract import authorize_candidate_request



def _headers(**overrides):
    headers = {
        "X-Correlation-ID": "corr-candidate-1",
        "X-Tenant-ID": "tenant-a",
        "Idempotency-Key": "attempt-1",
        "X-Request-Deadline": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
    }
    headers.update(overrides)
    return headers


def test_candidate_route_is_fail_closed_without_verified_principal(client):
    response = client.post(
        "/candidate/generate-policy",
        json={},
        headers={"Authorization": "Bearer spoofed", "X-Service-Identity": "docker-agent"},
    )

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "service_authentication_required"


def test_candidate_contract_rejects_tenant_mismatch(app):
    with app.test_request_context("/candidate/generate-policy", method="POST", headers=_headers()):
        g.service_principal = {
            "identity": "docker-agent",
            "audience": "policy-agent",
            "scopes": ["policy:candidate:generate"],
            "tenant_id": "tenant-b",
        }
        metadata, error = authorize_candidate_request(
            audience="policy-agent",
            scope="policy:candidate:generate",
        )

    assert metadata is None
    assert error[1] == 403
    assert error[0]["error_code"] == "candidate_tenant_forbidden"


def test_candidate_contract_stays_blocked_without_deadline_enforcer(app):
    with app.test_request_context("/candidate/generate-policy", method="POST", headers=_headers()):
        g.service_principal = {
            "identity": "docker-agent",
            "audience": "policy-agent",
            "scopes": ["policy:candidate:generate"],
            "tenant_id": "tenant-a",
        }
        metadata, error = authorize_candidate_request(
            audience="policy-agent",
            scope="policy:candidate:generate",
        )

    assert metadata is None
    assert error[1] == 503
    assert error[0]["error_code"] == "candidate_execution_unavailable"


def test_candidate_generation_uses_domain_code_without_persistence(client, workload_headers):
    payload = {
        "context_id": "ctx-candidate",
        "refined_prompt": "Generate an access control policy.",
        "language": "en",
        "model_version": "mock",
    }
    metadata = {
        "tenant_id": "tenant-a",
        "idempotency_key": "attempt-1",
        "deadline": datetime.now(timezone.utc) + timedelta(minutes=1),
    }
    before = {
        "policies": list(mongo.db.policies.find()),
        "configs": list(mongo.db.policy_configs.find()),
    }

    with (
        patch("app.routes.routes.authorize_candidate_request", return_value=(metadata, None)),
        patch("app.services.logic.run_with_agent", return_value={
            "text": "Candidate policy",
            "structured_plan": [],
            "retrieval_evidence": [],
        }) as run_agent,
    ):
        response = client.post("/candidate/generate-policy", json=payload, headers=_headers(**workload_headers("/candidate/generate-policy")))

    assert response.status_code == 200
    assert response.get_json()["ownership"] == {
        "owner_service": "policy-agent",
        "source_of_truth": False,
        "collection": None,
    }
    assert response.get_json()["candidate"]["authoritative"] is False
    assert list(mongo.db.policies.find()) == before["policies"]
    assert list(mongo.db.policy_configs.find()) == before["configs"]
    assert run_agent.call_args.kwargs["store_config"] is False


def test_candidate_route_enforces_fixed_bounded_json_limit(client, app, monkeypatch, workload_headers):
    monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 512 * 1024)
    response = client.post(
        "/candidate/generate-policy",
        data="x" * ((256 * 1024) + 1),
        content_type="application/json",
        headers=_headers(**workload_headers("/candidate/generate-policy")),
    )

    assert response.status_code == 413
    assert response.is_json
    assert response.get_json()["error_code"] == "request_too_large"


def test_candidate_contract_rejects_overflowing_deadline(app):
    headers = _headers(**{"X-Request-Deadline": "9999-12-31T23:59:59-23:59"})
    with app.test_request_context("/candidate/generate-policy", method="POST", headers=headers):
        g.service_principal = {
            "identity": "docker-agent",
            "audience": "policy-agent",
            "scopes": ["policy:candidate:generate"],
            "tenant_id": "tenant-a",
        }
        metadata, error = authorize_candidate_request(
            audience="policy-agent",
            scope="policy:candidate:generate",
        )

    assert metadata is None
    assert error[1] == 400
    assert error[0]["error_code"] == "candidate_deadline_invalid"


def test_candidate_route_accepts_service_identity_principal(client, workload_headers):
    payload = {
        "context_id": "ctx-candidate",
        "refined_prompt": "Generate an access control policy.",
        "language": "en",
        "model_version": "mock",
    }
    policy = {
        **payload,
        "policy_text": "Candidate policy",
        "ownership": {"owner_service": "policy-agent", "source_of_truth": False, "collection": None},
    }

    with patch("app.routes.routes.run_generation_pipeline", return_value={"success": True, "policy": policy}) as pipeline:
        response = client.post("/candidate/generate-policy", json=payload, headers=_headers(**workload_headers("/candidate/generate-policy")))

    assert response.status_code == 200
    assert response.get_json()["candidate"] == {
        "authoritative": False,
        "tenant_id": "tenant-a",
        "idempotency_key": "attempt-1",
    }
    pipeline.assert_called_once_with(payload, persist=False)
