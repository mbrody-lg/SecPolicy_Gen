from app import mongo
from app.services import logic
import app.routes.routes as routes_module


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
            "important_assets": "Medical records",
            "critical_assets": "Patient data",
            "current_security_operations": "Backups",
            "methodology": "ISO 27001",
            "generic": "Specific",
            "need": "Protect patient data",
        },
    )

    assert response.status_code == 302
    context = mongo.db.contexts.find_one({"sector": "Healthcare"})
    assert context["security_context"]["analysis"]["confidence"] == "medium"

    mongo.db.contexts.update_one(
        {"_id": context["_id"]},
        {"$set": {"refined_prompt": "Protect patient data under GDPR."}},
    )

    payload = logic.get_context_and_prompt(str(context["_id"]))

    assert payload["refined_prompt"] == "Protect patient data under GDPR."
    assert payload["business_context"]["country"] == "Spain"
    assert payload["business_context"]["sector"] == "Healthcare"
    assert payload["business_context"]["critical_assets"] == ["Patient data"]
    assert payload["business_context"]["data_types"] == ["health_data"]
    assert "risk_methodologies" in payload["business_context"]["retrieval_collection_families"]
