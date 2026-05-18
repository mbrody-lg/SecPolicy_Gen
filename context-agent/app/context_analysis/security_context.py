"""Versioned security context contract for company information-security analysis."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

SECURITY_CONTEXT_VERSION = "1.0"

MAX_STRING_LENGTH = 1000
MAX_LIST_ITEMS = 25
MAX_FACTS = 80

REQUIRED_SECTIONS = (
    "profile",
    "information_assets",
    "compliance",
    "security_posture",
    "policy_intent",
    "analysis",
    "retrieval_hints",
)

LIST_FIELDS = {
    ("profile", "operating_countries"),
    ("profile", "languages"),
    ("information_assets", "important_assets"),
    ("information_assets", "critical_assets"),
    ("information_assets", "data_categories"),
    ("information_assets", "third_party_dependencies"),
    ("information_assets", "cloud_services"),
    ("compliance", "jurisdictions"),
    ("compliance", "regulatory_hints"),
    ("compliance", "methodologies"),
    ("security_posture", "current_controls"),
    ("security_posture", "known_gaps"),
    ("analysis", "missing_information"),
    ("retrieval_hints", "collection_families"),
    ("retrieval_hints", "jurisdictions"),
    ("retrieval_hints", "sectors"),
    ("retrieval_hints", "data_types"),
    ("retrieval_hints", "methodologies"),
}

STRING_FIELDS = {
    ("profile", "sector"),
    ("profile", "activity"),
    ("profile", "region"),
    ("profile", "size_band"),
    ("profile", "business_model"),
    ("profile", "service_type"),
    ("security_posture", "maturity"),
    ("security_posture", "risk_tolerance"),
    ("security_posture", "governance_owner"),
    ("policy_intent", "need"),
    ("policy_intent", "policy_type"),
    ("policy_intent", "scope"),
    ("policy_intent", "exclusions"),
    ("policy_intent", "audience"),
    ("policy_intent", "language"),
    ("policy_intent", "specificity"),
}

FACT_SOURCE_VALUES = {"provided", "derived", "provider", "default", "unknown"}


@dataclass(frozen=True)
class SecurityContextValidationError(ValueError):
    """Raised when a security context payload breaks the contract."""

    error_code: str
    field_path: str
    message: str

    def __str__(self) -> str:
        return f"{self.error_code}: {self.field_path}: {self.message}"


def build_security_context_from_answers(
    answers: dict[str, Any],
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Build a contract-shaped context from current Context Agent answer fields.

    This adapter only maps directly provided answers. Inference and enrichment
    belong to later INIT-05 slices.
    """
    normalized_answers = {
        str(key).strip(): _normalize_optional_string(value)
        for key, value in answers.items()
    }
    country = normalized_answers.get("country")
    region = normalized_answers.get("region")
    sector = normalized_answers.get("sector")
    important_assets = _split_terms(normalized_answers.get("important_assets"))
    critical_assets = _split_terms(normalized_answers.get("critical_assets"))
    current_controls = _split_terms(normalized_answers.get("current_security_operations"))
    methodologies = _split_terms(normalized_answers.get("methodology"))
    need = normalized_answers.get("need")
    specificity = normalized_answers.get("generic")
    explicit_data_categories = _split_terms(normalized_answers.get("data_categories"))
    explicit_regulatory_hints = _split_terms(normalized_answers.get("regulatory_hints"))
    analysis_text = " ".join(answer for answer in normalized_answers.values() if answer)
    data_categories = _dedupe(explicit_data_categories + _infer_data_categories(analysis_text))
    regulatory_hints = _dedupe(explicit_regulatory_hints + _infer_regulatory_hints(analysis_text))
    cloud_services = _dedupe(
        _split_terms(normalized_answers.get("cloud_services"))
        + _infer_cloud_services(analysis_text)
    )
    third_party_dependencies = _dedupe(
        _split_terms(normalized_answers.get("third_party_dependencies"))
        + _infer_third_party_dependencies(analysis_text)
    )

    context = _empty_security_context()
    context["profile"].update(
        {
            "operating_countries": [country] if country else [],
            "region": region,
            "sector": sector,
            "activity": normalized_answers.get("company_activity"),
            "size_band": normalized_answers.get("company_size"),
            "languages": [language] if language else [],
            "business_model": normalized_answers.get("business_model"),
            "service_type": normalized_answers.get("service_type"),
        }
    )
    context["information_assets"].update(
        {
            "important_assets": important_assets,
            "critical_assets": critical_assets,
            "data_categories": data_categories,
            "third_party_dependencies": third_party_dependencies,
            "cloud_services": cloud_services,
        }
    )
    context["compliance"].update(
        {
            "jurisdictions": [country] if country else [],
            "regulatory_hints": regulatory_hints,
            "methodologies": methodologies,
        }
    )
    context["security_posture"].update(
        {
            "current_controls": current_controls,
            "maturity": normalized_answers.get("security_maturity"),
            "known_gaps": _split_terms(normalized_answers.get("known_gaps")),
            "risk_tolerance": normalized_answers.get("risk_tolerance"),
            "governance_owner": normalized_answers.get("governance_owner"),
        }
    )
    context["policy_intent"].update(
        {
            "need": need,
            "policy_type": normalized_answers.get("policy_type"),
            "scope": normalized_answers.get("policy_scope"),
            "exclusions": normalized_answers.get("policy_exclusions"),
            "audience": normalized_answers.get("policy_audience"),
            "language": normalized_answers.get("language") or language,
            "specificity": specificity,
        }
    )
    context["retrieval_hints"].update(
        {
            "jurisdictions": [country] if country else [],
            "sectors": [sector] if sector else [],
            "data_types": data_categories,
            "methodologies": methodologies,
        }
    )
    context["retrieval_hints"]["collection_families"] = _infer_collection_families(context)
    context["analysis"]["facts"] = _provided_facts(normalized_answers)
    context["analysis"]["missing_information"] = _missing_information(context)
    context["analysis"]["confidence"] = _confidence(context)

    return validate_security_context(context)


def validate_security_context(value: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a security context payload."""
    if not isinstance(value, dict):
        raise SecurityContextValidationError(
            "security_context_invalid_type",
            "security_context",
            "Security context must be an object.",
        )

    payload = deepcopy(value)
    version = _normalize_optional_string(payload.get("version"))
    if version != SECURITY_CONTEXT_VERSION:
        raise SecurityContextValidationError(
            "security_context_version_unsupported",
            "version",
            f"Security context version must be {SECURITY_CONTEXT_VERSION}.",
        )

    for section in REQUIRED_SECTIONS:
        if not isinstance(payload.get(section), dict):
            raise SecurityContextValidationError(
                "security_context_section_invalid",
                section,
                "Required section must be an object.",
            )

    for section, field in LIST_FIELDS:
        payload[section][field] = _validate_string_list(
            payload[section].get(field, []),
            f"{section}.{field}",
        )

    for section, field in STRING_FIELDS:
        payload[section][field] = _validate_optional_string(
            payload[section].get(field),
            f"{section}.{field}",
        )

    payload["analysis"]["confidence"] = _validate_confidence(
        payload["analysis"].get("confidence"),
        "analysis.confidence",
    )
    payload["analysis"]["facts"] = _validate_facts(
        payload["analysis"].get("facts", []),
        "analysis.facts",
    )
    return payload


def _empty_security_context() -> dict[str, Any]:
    return {
        "version": SECURITY_CONTEXT_VERSION,
        "profile": {
            "sector": None,
            "activity": None,
            "size_band": None,
            "region": None,
            "operating_countries": [],
            "languages": [],
            "business_model": None,
            "service_type": None,
        },
        "information_assets": {
            "important_assets": [],
            "critical_assets": [],
            "data_categories": [],
            "third_party_dependencies": [],
            "cloud_services": [],
        },
        "compliance": {
            "jurisdictions": [],
            "regulatory_hints": [],
            "methodologies": [],
        },
        "security_posture": {
            "current_controls": [],
            "maturity": None,
            "known_gaps": [],
            "risk_tolerance": None,
            "governance_owner": None,
        },
        "policy_intent": {
            "need": None,
            "policy_type": None,
            "scope": None,
            "exclusions": None,
            "audience": None,
            "language": None,
            "specificity": None,
        },
        "analysis": {
            "facts": [],
            "missing_information": [],
            "confidence": "low",
        },
        "retrieval_hints": {
            "collection_families": [],
            "jurisdictions": [],
            "sectors": [],
            "data_types": [],
            "methodologies": [],
        },
    }


def _provided_facts(answers: dict[str, str | None]) -> list[dict[str, str]]:
    facts = []
    for field, answer in sorted(answers.items()):
        if answer:
            facts.append(
                {
                    "field": field,
                    "source": "provided",
                    "value": answer,
                }
            )
    return facts[:MAX_FACTS]


def _missing_information(context: dict[str, Any]) -> list[str]:
    missing = []
    if not context["profile"]["sector"]:
        missing.append("profile.sector")
    if not context["profile"]["operating_countries"]:
        missing.append("profile.operating_countries")
    if not context["information_assets"]["critical_assets"]:
        missing.append("information_assets.critical_assets")
    if not context["policy_intent"]["need"]:
        missing.append("policy_intent.need")
    return missing


def _confidence(context: dict[str, Any]) -> str:
    missing = context["analysis"]["missing_information"]
    if not missing and context["information_assets"]["important_assets"]:
        return "medium"
    if len(missing) <= 2:
        return "low"
    return "very_low"


def _validate_facts(value: Any, field_path: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise SecurityContextValidationError(
            "security_context_invalid_facts",
            field_path,
            "Facts must be a list.",
        )
    if len(value) > MAX_FACTS:
        raise SecurityContextValidationError(
            "security_context_too_many_facts",
            field_path,
            f"Facts must contain at most {MAX_FACTS} items.",
        )

    normalized = []
    for index, item in enumerate(value):
        item_path = f"{field_path}.{index}"
        if not isinstance(item, dict):
            raise SecurityContextValidationError(
                "security_context_invalid_fact",
                item_path,
                "Fact must be an object.",
            )
        field = _required_string(item.get("field"), f"{item_path}.field")
        source = _required_string(item.get("source"), f"{item_path}.source")
        fact_value = _required_string(item.get("value"), f"{item_path}.value")
        if source not in FACT_SOURCE_VALUES:
            raise SecurityContextValidationError(
                "security_context_invalid_fact_source",
                f"{item_path}.source",
                "Fact source is not allowed.",
            )
        normalized.append({"field": field, "source": source, "value": fact_value})
    return normalized


def _validate_string_list(value: Any, field_path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SecurityContextValidationError(
            "security_context_invalid_list",
            field_path,
            "Field must be a list of strings.",
        )
    if len(value) > MAX_LIST_ITEMS:
        raise SecurityContextValidationError(
            "security_context_list_too_long",
            field_path,
            f"Field must contain at most {MAX_LIST_ITEMS} items.",
        )
    return [_required_string(item, f"{field_path}.{index}") for index, item in enumerate(value)]


def _validate_optional_string(value: Any, field_path: str) -> str | None:
    if value is None:
        return None
    normalized = _required_string(value, field_path)
    return normalized or None


def _required_string(value: Any, field_path: str) -> str:
    normalized = _normalize_optional_string(value)
    if normalized is None:
        raise SecurityContextValidationError(
            "security_context_invalid_string",
            field_path,
            "Field must be a string.",
        )
    if len(normalized) > MAX_STRING_LENGTH:
        raise SecurityContextValidationError(
            "security_context_string_too_long",
            field_path,
            f"Field must contain at most {MAX_STRING_LENGTH} characters.",
        )
    return normalized


def _validate_confidence(value: Any, field_path: str) -> str:
    confidence = _required_string(value, field_path)
    if confidence not in {"very_low", "low", "medium", "high"}:
        raise SecurityContextValidationError(
            "security_context_invalid_confidence",
            field_path,
            "Confidence value is not allowed.",
        )
    return confidence


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _split_terms(value: str | None) -> list[str]:
    if not value:
        return []
    separators = [",", ";", "\n"]
    terms = [value]
    for separator in separators:
        terms = [part for term in terms for part in term.split(separator)]
    return [term.strip() for term in terms if term.strip()]


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _infer_data_categories(text: str) -> list[str]:
    normalized = text.lower()
    categories = []
    if _contains_any(normalized, ("personal data", "datos personales", "gdpr", "rgpd", "customer database")):
        categories.append("personal_data")
    if _contains_any(normalized, ("health", "healthcare", "medical", "patient", "salud", "paciente")):
        categories.append("health_data")
    if _contains_any(
        normalized,
        (
            "employee data",
            "employee records",
            "employee files",
            "hr data",
            "hr operations",
            "payroll",
            "rrhh",
            "nomina",
            "nómina",
        ),
    ):
        categories.append("employee_data")
    if _contains_any(normalized, ("payment", "online payment", "card", "pago", "e-commerce", "ecommerce")):
        categories.append("commerce_data")
    return categories


def _infer_regulatory_hints(text: str) -> list[str]:
    normalized = text.lower()
    hints = []
    if _contains_any(normalized, ("gdpr", "rgpd")):
        hints.append("gdpr")
    if "iso 27001" in normalized:
        hints.append("iso_27001")
    if "iso 27799" in normalized:
        hints.append("iso_27799")
    if "cis controls" in normalized or "cis control" in normalized:
        hints.append("cis_controls")
    return hints


def _infer_cloud_services(text: str) -> list[str]:
    normalized = text.lower()
    services = []
    if _contains_any(normalized, ("hosting", "cloud", "saas", "web platform", "web application")):
        services.append("hosted_web_platform")
    return services


def _infer_third_party_dependencies(text: str) -> list[str]:
    normalized = text.lower()
    dependencies = []
    if _contains_any(normalized, ("hosting", "provider", "saas", "plugin", "plugins")):
        dependencies.append("external_service_provider")
    if _contains_any(normalized, ("payment", "online payment", "pago")):
        dependencies.append("payment_provider")
    return dependencies


def _infer_collection_families(context: dict[str, Any]) -> list[str]:
    families = ["legal_norms"]
    if context["profile"]["sector"]:
        families.append("sector_norms")
    if context["compliance"]["methodologies"] or context["compliance"]["regulatory_hints"]:
        families.append("security_frameworks")
    if context["information_assets"]["critical_assets"]:
        families.append("risk_methodologies")
    if context["security_posture"]["current_controls"]:
        families.append("implementation_guides")
    return families


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)
