from pathlib import Path

import pytest
import yaml

from app.context_analysis import (
    SECURITY_CONTEXT_VERSION,
    SecurityContextValidationError,
    build_security_context_from_answers,
    validate_security_context,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "app" / "config" / "examples" / "answers"


def _answers_from_fixture(name):
    payload = yaml.safe_load((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return {item["id"]: item["answer"] for item in payload["answers"]}


def test_build_security_context_maps_current_healthcare_answers():
    context = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )

    assert context["version"] == SECURITY_CONTEXT_VERSION
    assert context["profile"]["operating_countries"] == ["Spain"]
    assert context["profile"]["region"] == "Valencian Community"
    assert context["profile"]["sector"] == "Private healthcare"
    assert context["profile"]["languages"] == ["en"]
    assert context["information_assets"]["important_assets"] == [
        "Medical records",
        "digital equipment",
        "management application.",
    ]
    assert context["information_assets"]["critical_assets"] == [
        "Medical data and backup systems."
    ]
    assert context["compliance"]["methodologies"] == [
        "GDPR and ISO 27799 should be applied."
    ]
    assert context["compliance"]["regulatory_hints"] == ["gdpr", "iso_27799"]
    assert context["information_assets"]["data_categories"] == [
        "personal_data",
        "health_data",
    ]
    assert context["security_posture"]["current_controls"] == [
        "Antivirus protection",
        "local copies",
        "password access.",
    ]
    assert context["policy_intent"]["need"] == "Comply with GDPR and protect patient data."
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
    assert context["information_assets"]["critical_assets"] == [
        "Sales website and online payment system."
    ]
    assert context["information_assets"]["data_categories"] == [
        "personal_data",
        "commerce_data",
    ]
    assert context["information_assets"]["cloud_services"] == ["hosted_web_platform"]
    assert context["information_assets"]["third_party_dependencies"] == [
        "external_service_provider",
        "payment_provider",
    ]
    assert context["compliance"]["regulatory_hints"] == ["cis_controls"]
    assert context["policy_intent"]["specificity"] == "Generics adapted to e-commerce."
    assert context["retrieval_hints"]["jurisdictions"] == ["France"]
    assert context["retrieval_hints"]["data_types"] == [
        "personal_data",
        "commerce_data",
    ]
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


def test_validate_security_context_rejects_invalid_fact_source():
    payload = build_security_context_from_answers(
        _answers_from_fixture("clinica_dental.yaml"),
        language="en",
    )
    payload["analysis"]["facts"][0]["source"] = "provider"

    with pytest.raises(SecurityContextValidationError) as error:
        validate_security_context(payload)

    assert error.value.error_code == "security_context_invalid_fact_source"
    assert error.value.field_path == "analysis.facts.0.source"


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
