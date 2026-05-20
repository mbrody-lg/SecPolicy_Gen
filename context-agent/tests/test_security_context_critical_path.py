from app import mongo
from app.services import logic
import app.routes.routes as routes_module
from bson import ObjectId


def test_security_context_create_to_policy_payload_contract(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "run_with_agent",
        lambda prompt, context_id, model_version=None: "Refined healthcare context",
    )

    response = client.post(
        "/create",
        data={
            "country": "Spain",
            "region": "Catalonia",
            "sector": "Healthcare",
            "company_activity": "Private outpatient clinic",
            "important_assets": "Medical records",
            "critical_assets": "Patient data",
            "data_categories": "health_data",
            "third_party_dependencies": "external laboratory",
            "current_security_operations": "Backups",
            "methodology": "ISO 27001",
            "generic": "Specific",
            "policy_type": "Access control policy",
            "need": "Protect patient data",
        },
    )

    assert response.status_code == 302
    context_id = response.location.rsplit("/", 1)[-1]
    context = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
    assert context["security_context"]["analysis"]["confidence"] == "medium"
    assert context["security_context"]["profile"]["activity"] == "Private outpatient clinic"

    approved_plan = logic.approve_context_intelligence_plan({
        **context,
        "context_intelligence_plan": logic.build_context_intelligence_plan(context),
    })
    mongo.db.contexts.update_one(
        {"_id": context["_id"]},
        {
            "$set": {
                "context_intelligence_plan": approved_plan,
                "context_task_results": {
                    "version": "1.0",
                    "status": "completed",
                    "plan_revision_id": "plan-rev-1",
                    "context_snapshot_hash": approved_plan["review"]["context_snapshot_hash"],
                    "tasks": [
                        {
                            "task_id": "information_assets",
                            "title": "Information assets",
                            "status": "completed",
                            "result": "Patient data and medical records require GDPR-aligned controls.",
                        }
                    ],
                },
            }
        },
    )
    synthesis = logic.synthesize_final_context(str(context["_id"]))
    assert synthesis["success"] is True

    payload = logic.get_context_and_prompt(str(context["_id"]))

    assert "Patient data" in payload["refined_prompt"]
    assert payload["business_context"]["country"] == "Spain"
    assert payload["business_context"]["sector"] == "Healthcare"
    assert payload["business_context"]["critical_assets"] == ["Patient data"]
    assert payload["business_context"]["data_types"] == ["health_data"]
    assert "risk_methodologies" in payload["business_context"]["retrieval_collection_families"]
