from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from flask import g

from app.agents.roles.coordinator import Coordinator
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
        "/candidate/validate-policy",
        json={},
        headers={"Authorization": "Bearer spoofed", "X-Service-Identity": "docker-agent"},
    )

    assert response.status_code == 503
    assert response.get_json()["error_code"] == "candidate_identity_unavailable"


def test_candidate_contract_rejects_tenant_mismatch(app):
    with app.test_request_context("/candidate/validate-policy", method="POST", headers=_headers()):
        g.service_principal = {
            "identity": "docker-agent",
            "audience": "validator-agent",
            "scopes": ["policy:candidate:validate"],
            "tenant_id": "tenant-b",
        }
        metadata, error = authorize_candidate_request(
            audience="validator-agent",
            scope="policy:candidate:validate",
        )

    assert metadata is None
    assert error[1] == 403
    assert error[0]["error_code"] == "candidate_tenant_forbidden"


def test_read_only_validation_runs_once_without_side_effects():
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.validation = {"rounds": 3, "consensus_threshold": 2, "vote_strategy": "majority"}
    coordinator.debug_mode = False
    coordinator.agent = MagicMock()
    coordinator.agent.roles = [{"AWC": {}}, {"AWL": {}}, {"EVA": {}}]
    coordinator.agent.run.return_value = [
        {"role": "AWC", "status": "review", "reason": "Missing scope", "recommendations": ["Add scope"]},
        {"role": "AWL", "status": "accepted"},
    ]
    coordinator.evaluator = MagicMock()
    coordinator.evaluator.evaluate.return_value = {"status": "review"}
    coordinator.log_validation = MagicMock()

    with patch("app.services.logic.send_policy_update_to_policy_agent") as update_policy:
        result = coordinator.validate_policy({
            "context_id": "ctx-candidate",
            "policy_text": "Candidate policy",
            "generated_at": "2026-07-16T00:00:00+00:00",
        }, read_only=True)

    assert result["status"] == "review"
    assert coordinator.agent.run.call_count == 1
    assert coordinator.evaluator.evaluate.call_count == 1
    coordinator.log_validation.assert_not_called()
    update_policy.assert_not_called()


def test_candidate_validation_route_preserves_authoritative_store(client):
    payload = {
        "context_id": "ctx-candidate",
        "policy_text": "Candidate policy",
        "structured_plan": [],
        "generated_at": "2026-07-16T00:00:00+00:00",
    }
    metadata = {
        "tenant_id": "tenant-a",
        "idempotency_key": "attempt-1",
        "deadline": datetime.now(timezone.utc) + timedelta(minutes=1),
    }
    validation = {
        **payload,
        "language": "en",
        "policy_agent_version": "0.1.0",
        "status": "accepted",
        "reasons": [],
        "recommendations": [],
        "ownership": {"owner_service": "validator-agent", "source_of_truth": False, "collection": None},
    }

    with (
        patch("app.routes.routes.authorize_candidate_request", return_value=(metadata, None)),
        patch("app.routes.routes.run_validation_pipeline", return_value={
            "success": True,
            "stage": "completed",
            "validation": validation,
        }) as pipeline,
    ):
        response = client.post("/candidate/validate-policy", json=payload)

    assert response.status_code == 200
    assert response.get_json()["candidate"]["authoritative"] is False
    assert pipeline.call_args.kwargs["read_only"] is True
