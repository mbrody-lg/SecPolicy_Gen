"""Tenant-bound authoritative Policy persistence regression tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import patch

import pytest
from pymongo.errors import PyMongoError

from app import mongo
from app.policy_persistence import initialize_policy_index
from app.services import logic
from app.workload_token import mint_token
from workload_test_keys import KEY_IDS, signing_key


TENANT_A = "tenant-a"
TENANT_B = "another-organization"
CONTEXT_ID = "6825a0e00194d322881db128"
UPDATE_PATH = f"/generate_policy/{CONTEXT_ID}/update"


def _headers(path, tenant_id=TENANT_A):
    subject, scope = (
        ("context-agent", "policy:generate") if path == "/generate_policy"
        else ("validator-agent", "policy:update")
    )
    token = mint_token(
        key=signing_key(subject), kid=KEY_IDS[subject], subject=subject,
        audience="policy-agent", scope=scope, tenant_id=tenant_id,
        path=path, context_id=CONTEXT_ID,
    )
    return {"Authorization": f"Bearer {token}"}


def _generation(context_id=CONTEXT_ID):
    return {
        "context_id": context_id,
        "refined_prompt": "Generate a synthetic access policy.",
        "language": "en",
        "model_version": "client-selected-version",
    }


def _feedback(context_id=CONTEXT_ID):
    return {
        "context_id": context_id,
        "language": "en",
        "policy_text": "Previous synthetic policy",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": ["Needs clarification"],
        "recommendations": ["Clarify access control"],
    }


def _policy(organization_id=TENANT_A, context_id=CONTEXT_ID, revision_count=0):
    return {
        "organization_id": organization_id,
        "context_id": context_id,
        "language": "en",
        "policy_text": "Previous synthetic policy",
        "model_version": "client-selected-version",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lifecycle_status": "generated",
        "revision_count": revision_count,
        "ownership": {
            "owner_service": "policy-agent",
            "source_of_truth": True,
            "collection": "policies",
        },
    }


def test_generation_uses_verified_principal_not_body_or_header(client):
    payload = {**_generation(), "tenant_id": TENANT_B, "organization_id": TENANT_B}
    with patch("app.services.logic.run_with_agent", return_value={"text": "Synthetic policy"}) as agent:
        response = client.post(
            "/generate_policy", json=payload,
            headers=_headers("/generate_policy"),
        )

    assert response.status_code == 200
    assert response.get_json()["organization_id"] == TENANT_A
    assert mongo.db.policies.find_one({"organization_id": TENANT_A})["policy_text"] == "Synthetic policy"
    assert mongo.db.policies.count_documents({"organization_id": TENANT_B}) == 0
    assert mongo.db.policy_configs.count_documents({}) == 0
    agent.assert_called_once()


def test_same_model_version_different_tenants_does_not_write_global_config(client):
    mongo.db.policy_configs.insert_one({"model_version": "client-selected-version", "sentinel": "unchanged"})
    original_configs = list(mongo.db.policy_configs.find())
    with patch("app.services.logic.run_with_agent", return_value={"text": "Synthetic policy"}) as agent:
        for tenant in (TENANT_A, TENANT_B):
            response = client.post(
                "/generate_policy", json=_generation(),
                headers=_headers("/generate_policy", tenant_id=tenant),
            )
            assert response.status_code == 200
            assert response.get_json()["organization_id"] == tenant

    assert agent.call_count == 2
    assert mongo.db.policies.count_documents({"context_id": CONTEXT_ID}) == 2
    assert list(mongo.db.policy_configs.find()) == original_configs


@pytest.mark.parametrize("legacy", [False, True])
def test_foreign_and_tenantless_update_are_inaccessible_without_model_or_writes(
    client, legacy,
):
    stored = _policy()
    if legacy:
        del stored["organization_id"]
    mongo.db.policies.insert_one(stored)
    before = list(mongo.db.policies.find())
    with patch("app.services.logic.update_with_agent") as agent:
        response = client.post(
            UPDATE_PATH, json=_feedback(),
            headers=_headers(
                UPDATE_PATH,
                tenant_id=TENANT_A if legacy else TENANT_B,
            ),
        )

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "policy_not_found"
    agent.assert_not_called()
    assert list(mongo.db.policies.find()) == before
    assert mongo.db.policy_configs.count_documents({}) == 0


def test_update_only_changes_policy_owned_by_verified_tenant(client):
    mongo.db.policies.insert_many([_policy(TENANT_A), _policy(TENANT_B)])
    other_before = mongo.db.policies.find_one({"organization_id": TENANT_B})
    with patch("app.services.logic.update_with_agent", return_value={"text": "Revised synthetic policy"}) as agent:
        response = client.post(
            UPDATE_PATH, json=_feedback(),
            headers=_headers(UPDATE_PATH),
        )

    assert response.status_code == 200
    assert response.get_json()["organization_id"] == TENANT_A
    assert mongo.db.policies.find_one({"organization_id": TENANT_A})["revision_count"] == 1
    assert mongo.db.policies.find_one({"organization_id": TENANT_B}) == other_before
    assert mongo.db.policy_configs.count_documents({}) == 0
    agent.assert_called_once()


def test_duplicate_authoritative_rows_are_ambiguous_before_model(client):
    mongo.db.policies.insert_many([_policy(), _policy()])
    before = list(mongo.db.policies.find())
    with patch("app.services.logic.update_with_agent") as agent:
        response = client.post(
            UPDATE_PATH, json=_feedback(),
            headers=_headers(UPDATE_PATH),
        )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "policy_ambiguous"
    agent.assert_not_called()
    assert list(mongo.db.policies.find()) == before


def test_existing_policy_blocks_duplicate_generation_before_model(client):
    mongo.db.policies.insert_one(_policy())
    before = list(mongo.db.policies.find())
    with patch("app.services.logic.run_with_agent") as agent:
        response = client.post(
            "/generate_policy", json=_generation(),
            headers=_headers("/generate_policy"),
        )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "policy_already_exists"
    agent.assert_not_called()
    assert list(mongo.db.policies.find()) == before


def test_concurrent_generation_can_persist_only_one_authoritative_policy(app, app_context):
    initialize_policy_index(mongo.db)
    barrier = Barrier(2)

    def fake_generation(**_kwargs):
        barrier.wait(timeout=5)
        return {"text": "Synthetic concurrent policy"}

    def generate():
        with app.app_context():
            return logic.run_generation_pipeline(_generation(), organization_id=TENANT_A)

    with patch("app.services.logic.run_with_agent", side_effect=fake_generation):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: generate(), range(2)))

    assert sorted(result.get("status_code", 200) for result in results) == [200, 409]
    assert {result.get("error_code") for result in results if not result["success"]} == {"policy_already_exists"}
    assert mongo.db.policies.count_documents({"organization_id": TENANT_A, "context_id": CONTEXT_ID}) == 1


@pytest.mark.parametrize("invalid", [
    {"ownership": None},
    {"ownership": {"source_of_truth": False}},
    {"lifecycle_status": "candidate"},
    {"revision_count": -1},
    {"revision_count": True},
])
def test_non_authoritative_policy_fails_before_model(client, invalid):
    mongo.db.policies.insert_one({**_policy(), **invalid})
    before = list(mongo.db.policies.find())
    with patch("app.services.logic.update_with_agent") as agent:
        response = client.post(
            UPDATE_PATH, json=_feedback(), headers=_headers(UPDATE_PATH),
        )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "policy_not_authoritative"
    agent.assert_not_called()
    assert list(mongo.db.policies.find()) == before


def test_stale_feedback_fails_before_model(client):
    mongo.db.policies.insert_one(_policy())
    before = list(mongo.db.policies.find())
    with patch("app.services.logic.update_with_agent") as agent:
        response = client.post(
            UPDATE_PATH,
            json={**_feedback(), "policy_text": "Older policy revision"},
            headers=_headers(UPDATE_PATH),
        )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "policy_revision_conflict"
    agent.assert_not_called()
    assert list(mongo.db.policies.find()) == before


def test_update_revision_cas_prevents_stale_overwrite(client):
    mongo.db.policies.insert_one(_policy())

    def concurrent_revision(**_kwargs):
        mongo.db.policies.update_one(
            {"organization_id": TENANT_A},
            {"$set": {"revision_count": 1, "policy_text": "Concurrent policy"}},
        )
        return {"text": "Stale model result"}

    with patch("app.services.logic.update_with_agent", side_effect=concurrent_revision):
        response = client.post(
            UPDATE_PATH, json=_feedback(),
            headers=_headers(UPDATE_PATH),
        )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "policy_revision_conflict"
    assert mongo.db.policies.find_one({"organization_id": TENANT_A})["policy_text"] == "Concurrent policy"
    assert mongo.db.policy_configs.count_documents({}) == 0


def test_real_update_flow_never_writes_request_time_global_config(
    client, monkeypatch,
):
    class FakeAgent:
        roles = ["update"]

        def run(self, *_args):
            return {"text": "Revised synthetic policy"}

    config = {"type": "mock", "model": "configured-model"}
    monkeypatch.setattr(logic, "load_policy_config", lambda: config)
    monkeypatch.setattr(logic, "create_agent_from_config", lambda _config: FakeAgent())
    mongo.db.policies.insert_one(_policy())
    mongo.db.policy_configs.insert_one({"model_version": "client-selected-version", "sentinel": "unchanged"})
    original_configs = list(mongo.db.policy_configs.find())

    response = client.post(
        UPDATE_PATH, json=_feedback(), headers=_headers(UPDATE_PATH),
    )

    assert response.status_code == 200
    assert response.get_json()["policy_text"] == "Revised synthetic policy"
    assert list(mongo.db.policy_configs.find()) == original_configs


def test_nonpersist_generation_runs_agent_without_any_database_write(app_context, monkeypatch):
    class FakeAgent:
        def run(self, **_kwargs):
            return {"text": "Candidate synthetic policy"}

    monkeypatch.setattr(logic, "load_policy_config", lambda: {
        "type": "mock", "model": "configured-model",
    })
    monkeypatch.setattr(logic, "create_agent_from_config", lambda _config: FakeAgent())
    result = logic.run_generation_pipeline(_generation(), persist=False)

    assert result["success"] is True
    assert result["policy"]["lifecycle_status"] == "candidate"
    assert result["policy"]["ownership"]["source_of_truth"] is False
    assert "organization_id" not in result["policy"]
    assert mongo.db.policies.count_documents({}) == 0
    assert mongo.db.policy_configs.count_documents({}) == 0


def test_missing_verified_organization_fails_before_model_or_writes(app_context):
    with patch("app.services.logic.run_with_agent") as agent:
        result = logic.run_generation_pipeline(_generation(), organization_id=None)
    assert result["status_code"] == 503
    assert result["error_code"] == "organization_identity_unavailable"
    agent.assert_not_called()
    assert mongo.db.policies.count_documents({}) == 0
    assert mongo.db.policy_configs.count_documents({}) == 0


def test_missing_verified_organization_blocks_update_before_model(app_context):
    mongo.db.policies.insert_one(_policy())
    before = list(mongo.db.policies.find())
    with patch("app.services.logic.update_with_agent") as agent:
        result = logic.run_policy_update_pipeline(
            _feedback(), CONTEXT_ID, organization_id=None,
        )
    assert result["status_code"] == 503
    assert result["error_code"] == "organization_identity_unavailable"
    agent.assert_not_called()
    assert list(mongo.db.policies.find()) == before


def test_policy_lookup_does_not_expose_database_errors(app_context):
    with patch.object(mongo.db.policies, "find_one", side_effect=PyMongoError("secret database host")):
        result = logic.run_generation_pipeline(_generation(), organization_id=TENANT_A)
    assert result["status_code"] == 503
    assert result["error_code"] == "policy_persistence_unavailable"
    assert "secret database host" not in str(result)


def test_generation_insert_failure_has_bounded_error(app_context):
    with (
        patch("app.services.logic.run_with_agent", return_value={"text": "Synthetic policy"}),
        patch.object(mongo.db.policies, "insert_one", side_effect=PyMongoError("secret database host")),
    ):
        result = logic.run_generation_pipeline(_generation(), organization_id=TENANT_A)

    assert result["status_code"] == 503
    assert result["error_code"] == "policy_persistence_unavailable"
    assert "secret database host" not in str(result)


def test_update_lookup_failure_is_bounded_and_skips_model(app_context):
    with (
        patch.object(mongo.db.policies, "find", side_effect=PyMongoError("secret database host")),
        patch("app.services.logic.update_with_agent") as agent,
    ):
        result = logic.run_policy_update_pipeline(
            _feedback(), CONTEXT_ID, organization_id=TENANT_A,
        )

    assert result["status_code"] == 503
    assert result["error_code"] == "policy_persistence_unavailable"
    assert "secret database host" not in str(result)
    agent.assert_not_called()


def test_update_write_failure_has_bounded_error(app_context):
    mongo.db.policies.insert_one(_policy())
    with (
        patch("app.services.logic.update_with_agent", return_value={"text": "Revised policy"}),
        patch.object(mongo.db.policies, "update_one", side_effect=PyMongoError("secret database host")),
    ):
        result = logic.run_policy_update_pipeline(
            _feedback(), CONTEXT_ID, organization_id=TENANT_A,
        )

    assert result["status_code"] == 503
    assert result["error_code"] == "policy_persistence_unavailable"
    assert "secret database host" not in str(result)
    assert mongo.db.policies.find_one({"organization_id": TENANT_A})["policy_text"] == "Previous synthetic policy"


def test_startup_indexes_guard_new_rows_without_requiring_legacy_uniqueness():
    with patch.object(mongo.db.policies, "create_index", return_value="organization_context_lookup") as create:
        initialize_policy_index(mongo.db)
    assert create.call_count == 2
    assert create.call_args_list[0].kwargs == {"name": "organization_context_lookup"}
    assert create.call_args_list[1].kwargs == {
        "name": "organization_context_generated_unique", "unique": True,
        "partialFilterExpression": {"generation_guard": True},
    }
    assert all(call.args[0] == [("organization_id", 1), ("context_id", 1)] for call in create.call_args_list)

    with patch.object(mongo.db.policies, "create_index", side_effect=PyMongoError("secret database host")):
        with pytest.raises(RuntimeError, match="Policy persistence index initialization failed") as error:
            initialize_policy_index(mongo.db)
    assert "secret database host" not in str(error.value)
