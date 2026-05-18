from app.rag.context import build_retrieval_context
from app.services.logic import validate_generation_payload


def test_init05_business_context_payload_is_policy_agent_compatible(app_context):
    payload = {
        "context_id": "ctx-init05-healthcare",
        "refined_prompt": "Protect patient data under GDPR.",
        "language": "en",
        "model_version": "1",
        "business_context": {
            "country": "Spain",
            "region": "Catalonia",
            "sector": "Healthcare",
            "important_assets": ["Medical records"],
            "critical_assets": ["Patient data"],
            "current_security_operations": "Backups",
            "methodology": "ISO 27001",
            "generic": "Specific",
            "need": "Protect patient data",
            "data_types": ["health_data"],
            "retrieval_collection_families": [
                "legal_norms",
                "sector_norms",
                "security_frameworks",
                "risk_methodologies",
                "implementation_guides",
            ],
        },
    }

    normalized = validate_generation_payload(payload)
    retrieval_context = build_retrieval_context(normalized)

    assert normalized["business_context"]["sector"] == "Healthcare"
    assert retrieval_context.country == "Spain"
    assert retrieval_context.sector == "Healthcare"
    assert retrieval_context.critical_assets == ["Patient data"]
    assert retrieval_context.methodology == "ISO 27001"
    assert retrieval_context.data_types == ["personal_data", "health_data"]
