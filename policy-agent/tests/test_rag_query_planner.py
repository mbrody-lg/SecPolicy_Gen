from pathlib import Path

from app.rag.context import build_retrieval_context
from app.rag.planner import build_retrieval_plan
from app.rag.sources import load_rag_source_manifest


def test_build_retrieval_context_extracts_business_context():
    context = build_retrieval_context(
        {
            "context_id": "ctx-health",
            "refined_prompt": "Protect patient data under GDPR.",
            "language": "en",
            "business_context": {
                "country": "Spain",
                "region": "Valencian Community",
                "sector": "Private healthcare",
                "important_assets": "Medical records, management application",
                "critical_assets": "Medical data; backups",
                "methodology": "GDPR and ISO 27799 should be applied",
                "generic": "Specific to healthcare",
                "need": "Comply with GDPR and protect patient data",
            },
        }
    )

    assert context.country == "Spain"
    assert context.sector == "Private healthcare"
    assert context.important_assets == ["Medical records", "management application"]
    assert context.critical_assets == ["Medical data", "backups"]
    assert context.data_types == ["personal_data", "health_data"]


def test_build_retrieval_plan_selects_expected_families_for_healthcare_context():
    manifest = load_rag_source_manifest(Path("app/config/rag_sources.yaml"))
    context = build_retrieval_context(
        {
            "context_id": "ctx-health",
            "refined_prompt": "Protect patient data under GDPR.",
            "language": "en",
            "business_context": {
                "country": "Spain",
                "sector": "Private healthcare",
                "critical_assets": "Medical data; backups",
                "methodology": "GDPR and ISO 27799 should be applied",
                "need": "Comply with GDPR and protect patient data",
            },
        }
    )

    plan = build_retrieval_plan(context, manifest)

    assert plan.required_families == [
        "legal_norms",
        "implementation_guides",
        "sector_norms",
        "security_frameworks",
        "risk_methodologies",
    ]
    assert plan.coverage_notes == []
    assert {step.collection for step in plan.steps} == {
        "normativa",
        "guia",
        "sector",
        "metodologia",
    }
    assert any(step.family == "legal_norms" and step.top_k == 4 for step in plan.steps)
    assert all(step.filters["collection_family"] == step.family for step in plan.steps)


def test_build_retrieval_plan_records_missing_family_coverage():
    context = build_retrieval_context(
        {
            "context_id": "ctx-sector",
            "refined_prompt": "Protect ecommerce customer data.",
            "language": "en",
            "business_context": {
                "country": "Spain",
                "sector": "Ecommerce",
            },
        }
    )
    manifest = {
        "sources": [
            {
                "id": "normativa",
                "collection": "normativa",
                "family": "legal_norms",
                "metadata": {"jurisdiction": ["EU"], "language": ["es"]},
            }
        ]
    }

    plan = build_retrieval_plan(context, manifest)

    assert plan.coverage_notes == [
        "missing_source_family:implementation_guides",
        "missing_source_family:sector_norms",
    ]

