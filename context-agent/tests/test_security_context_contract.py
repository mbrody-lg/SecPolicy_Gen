from pathlib import Path

import pytest
import yaml

from app.context_analysis import (
    SECURITY_CONTEXT_VERSION,
    SecurityContextValidationError,
    build_security_context_from_answers,
    merge_provider_enrichment,
    security_context_to_business_context,
    validate_security_context,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "app" / "config" / "examples" / "answers"
QUESTION_CONFIG = Path(__file__).resolve().parents[1] / "app" / "config" / "context_questions.yaml"


def _answers_from_fixture(name):
    payload = yaml.safe_load((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return {item["id"]: item["answer"] for item in payload["answers"]}


def _question_ids():
    payload = yaml.safe_load(QUESTION_CONFIG.read_text(encoding="utf-8"))
    return {item["id"] for item in payload["questions"]}


def test_example_answers_cover_full_context_questionnaire():
    expected_ids = _question_ids()

    for fixture_path in FIXTURE_DIR.glob("*.yaml"):
        answers = _answers_from_fixture(fixture_path.name)

        assert set(answers) == expected_ids
        assert all(str(answer).strip() for answer in answers.values())


def test_build_security_context_maps_current_healthcare_answers():
    context = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )

    assert context["version"] == SECURITY_CONTEXT_VERSION
    assert context["profile"]["operating_countries"] == ["Spain"]
    assert context["profile"]["region"] == "Valencian Community"
    assert context["profile"]["sector"] == "Private healthcare"
    assert context["profile"]["activity"].startswith("Dental clinic")
    assert context["profile"]["size_band"] == (
        "32 employees, 14 dentists and hygienists, 9 treatment rooms, "
        "and approximately 18,000 active patient records."
    )
    assert context["profile"]["business_model"].startswith("Private healthcare services")
    assert context["profile"]["languages"] == ["en"]
    assert "Medical records" in context["information_assets"]["important_assets"]
    assert "radiology images" in context["information_assets"]["important_assets"]
    assert "Patient clinical records" in context["information_assets"]["critical_assets"]
    assert "radiology image archive" in context["information_assets"]["critical_assets"]
    assert "GDPR" in context["compliance"]["methodologies"]
    assert "ISO 27799" in context["compliance"]["methodologies"]
    assert "and ISO 27002 should guide the security controls" in context["compliance"]["methodologies"]
    assert "GDPR" in context["compliance"]["regulatory_hints"]
    assert "ISO 27799" in context["compliance"]["regulatory_hints"]
    assert "health_data" in context["information_assets"]["data_categories"]
    assert "billing_data" in context["information_assets"]["data_categories"]
    assert "Dental practice SaaS provider" in context["information_assets"]["third_party_dependencies"]
    assert "Practice management SaaS" in context["information_assets"]["cloud_services"]
    assert "Antivirus protection" in context["security_posture"]["current_controls"]
    assert "supplier risk is not periodically assessed" in context["security_posture"]["known_gaps"]
    assert context["security_posture"]["maturity"].startswith("Intermediate operational maturity")
    assert context["security_posture"]["risk_tolerance"].startswith("Very low")
    assert context["security_posture"]["governance_owner"].startswith("Systems Manager")
    assert context["policy_intent"]["need"].startswith("Comply with GDPR")
    assert context["policy_intent"]["policy_type"] == (
        "Clinical systems access control and health data protection policy."
    )
    assert context["policy_intent"]["audience"].startswith("Dentists")
    assert context["retrieval_hints"]["sectors"] == ["Private healthcare"]
    assert context["retrieval_hints"]["collection_families"] == [
        "legal_norms",
        "sector_norms",
        "security_frameworks",
        "risk_methodologies",
        "implementation_guides",
    ]
    assert context["analysis"]["missing_information"] == []
    assert context["analysis"]["confidence"] == "medium"


def test_build_security_context_maps_current_ecommerce_answers():
    context = build_security_context_from_answers(
        _answers_from_fixture("botiga_online_artesania.yaml"),
        language="en",
    )

    assert context["profile"]["operating_countries"] == ["France"]
    assert context["profile"]["sector"] == "Craft e-commerce"
    assert context["profile"]["activity"].startswith("Online store")
    assert "Sales website" in context["information_assets"]["critical_assets"]
    assert "online payment flow" in context["information_assets"]["critical_assets"]
    assert "personal_data" in context["information_assets"]["data_categories"]
    assert "commerce_data" in context["information_assets"]["data_categories"]
    assert "Stripe dashboard" in context["information_assets"]["cloud_services"]
    assert "Shopify" in context["information_assets"]["third_party_dependencies"]
    assert "payment_provider" in context["information_assets"]["third_party_dependencies"]
    assert "cis_controls" in context["compliance"]["regulatory_hints"]
    assert context["policy_intent"]["specificity"].startswith("Specific policies adapted")
    assert context["policy_intent"]["policy_type"] == (
        "E-commerce access, supplier, and incident response policy."
    )
    assert context["retrieval_hints"]["jurisdictions"] == ["France"]
    assert "personal_data" in context["retrieval_hints"]["data_types"]
    assert "commerce_data" in context["retrieval_hints"]["data_types"]
    assert context["analysis"]["confidence"] == "medium"


def test_build_security_context_infers_employee_data_and_iso_27001():
    context = build_security_context_from_answers(
        {
            "country": "Spain",
            "sector": "HR consulting",
            "important_assets": "Employee files, payroll platform",
            "critical_assets": "Payroll and employee personal data",
            "current_security_operations": "SaaS identity provider",
            "methodology": "ISO 27001",
            "need": "Protect employee records and HR operations",
        },
        language="en",
    )

    assert context["information_assets"]["data_categories"] == [
        "personal_data",
        "employee_data",
    ]
    assert context["compliance"]["regulatory_hints"] == ["iso_27001"]
    assert context["information_assets"]["cloud_services"] == ["hosted_web_platform"]
    assert context["information_assets"]["third_party_dependencies"] == [
        "external_service_provider"
    ]


def test_build_security_context_maps_expanded_questionnaire_fields():
    context = build_security_context_from_answers(
        {
            "country": "Spain",
            "region": "Catalonia",
            "sector": "Healthcare",
            "company_activity": "Private outpatient clinic",
            "company_size": "25 employees",
            "business_model": "Private healthcare services",
            "service_type": "Hybrid physical and digital care",
            "important_assets": "Medical records",
            "critical_assets": "Patient data",
            "data_categories": "health_data, appointment_data",
            "third_party_dependencies": "external laboratory",
            "cloud_services": "managed hosting",
            "current_security_operations": "Backups",
            "known_gaps": "No formal access review",
            "regulatory_hints": "GDPR",
            "security_maturity": "basic",
            "risk_tolerance": "low",
            "governance_owner": "Clinic manager",
            "policy_type": "Access control policy",
            "policy_scope": "Clinical systems",
            "policy_exclusions": "Public website",
            "policy_audience": "Clinic staff",
            "language": "English",
            "generic": "Specific",
            "need": "Protect patient data",
        },
        language="en",
    )

    assert context["profile"]["activity"] == "Private outpatient clinic"
    assert context["profile"]["size_band"] == "25 employees"
    assert context["profile"]["business_model"] == "Private healthcare services"
    assert context["profile"]["service_type"] == "Hybrid physical and digital care"
    assert context["information_assets"]["data_categories"] == [
        "health_data",
        "appointment_data",
        "personal_data",
    ]
    assert "external laboratory" in context["information_assets"]["third_party_dependencies"]
    assert "managed hosting" in context["information_assets"]["cloud_services"]
    assert context["security_posture"]["known_gaps"] == ["No formal access review"]
    assert context["security_posture"]["maturity"] == "basic"
    assert context["security_posture"]["risk_tolerance"] == "low"
    assert context["security_posture"]["governance_owner"] == "Clinic manager"
    assert context["policy_intent"]["policy_type"] == "Access control policy"
    assert context["policy_intent"]["scope"] == "Clinical systems"
    assert context["policy_intent"]["exclusions"] == "Public website"
    assert context["policy_intent"]["audience"] == "Clinic staff"
    assert context["policy_intent"]["language"] == "English"


def test_security_context_to_business_context_flattens_policy_agent_fields():
    security_context = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )

    business_context = security_context_to_business_context(security_context)

    assert business_context["country"] == "Spain"
    assert business_context["region"] == "Valencian Community"
    assert business_context["sector"] == "Private healthcare"
    assert "Medical records" in business_context["important_assets"]
    assert "Patient clinical records" in business_context["critical_assets"]
    assert business_context["current_security_operations"].startswith("Antivirus protection")
    assert business_context["methodology"].startswith("GDPR, ISO 27799")
    assert business_context["generic"].startswith("Specific to private healthcare")
    assert business_context["need"].startswith("Comply with GDPR")
    assert "personal_data" in business_context["data_types"]
    assert "health_data" in business_context["data_types"]
    assert business_context["retrieval_collection_families"] == [
        "legal_norms",
        "sector_norms",
        "security_frameworks",
        "risk_methodologies",
        "implementation_guides",
    ]


def test_validate_security_context_rejects_missing_required_section():
    payload = {
        "version": SECURITY_CONTEXT_VERSION,
        "profile": {},
    }

    with pytest.raises(SecurityContextValidationError) as error:
        validate_security_context(payload)

    assert error.value.error_code == "security_context_section_invalid"
    assert error.value.field_path == "information_assets"


def test_validate_security_context_rejects_unsupported_version():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )
    payload["version"] = "2.0"

    with pytest.raises(SecurityContextValidationError) as error:
        validate_security_context(payload)

    assert error.value.error_code == "security_context_version_unsupported"
    assert error.value.field_path == "version"


def test_validate_security_context_rejects_oversized_values():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )
    payload["policy_intent"]["need"] = "x" * 1001

    with pytest.raises(SecurityContextValidationError) as error:
        validate_security_context(payload)

    assert error.value.error_code == "security_context_string_too_long"
    assert error.value.field_path == "policy_intent.need"


def test_validate_security_context_rejects_unknown_fact_source():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )
    payload["analysis"]["facts"][0]["source"] = "external_provider"

    with pytest.raises(SecurityContextValidationError) as error:
        validate_security_context(payload)

    assert error.value.error_code == "security_context_invalid_fact_source"
    assert error.value.field_path == "analysis.facts.0.source"


def test_merge_provider_enrichment_accepts_bounded_updates_and_facts():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )

    enriched = merge_provider_enrichment(
        payload,
        {
            "version": SECURITY_CONTEXT_VERSION,
            "updates": {
                "profile": {"activity": "Dental clinic"},
                "security_posture": {"maturity": "basic"},
                "information_assets": {
                    "data_categories": ["personal_data", "health_data"]
                },
            },
            "facts": [
                {
                    "field": "profile.activity",
                    "value": "Dental clinic inferred from healthcare context.",
                }
            ],
        },
    )

    assert enriched["profile"]["activity"] == "Dental clinic"
    assert enriched["security_posture"]["maturity"] == "basic"
    assert enriched["analysis"]["facts"][-1] == {
        "field": "profile.activity",
        "source": "provider",
        "value": "Dental clinic inferred from healthcare context.",
    }


def test_merge_provider_enrichment_rejects_unknown_fields():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )

    with pytest.raises(SecurityContextValidationError) as error:
        merge_provider_enrichment(
            payload,
            {
                "version": SECURITY_CONTEXT_VERSION,
                "updates": {"profile": {"raw_provider_payload": "not allowed"}},
            },
        )

    assert error.value.error_code == "security_context_enrichment_field_not_allowed"
    assert error.value.field_path == "updates.profile.raw_provider_payload"


def test_merge_provider_enrichment_rejects_unsupported_version():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )

    with pytest.raises(SecurityContextValidationError) as error:
        merge_provider_enrichment(payload, {"version": "2.0", "updates": {}})

    assert error.value.error_code == "security_context_enrichment_version_unsupported"


def test_build_security_context_reports_missing_core_information():
    context = build_security_context_from_answers(
        {
            "country": "",
            "sector": "",
            "important_assets": "Laptop fleet",
            "critical_assets": "",
            "need": "",
        },
        language="en",
    )

    assert context["analysis"]["missing_information"] == [
        "profile.sector",
        "profile.operating_countries",
        "information_assets.critical_assets",
        "policy_intent.need",
    ]
    assert context["analysis"]["confidence"] == "very_low"
