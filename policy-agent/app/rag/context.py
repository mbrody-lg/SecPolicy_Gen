"""Retrieval context extraction for policy-agent RAG."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalContext:
    """Structured business context used for deterministic retrieval planning."""

    context_id: str
    refined_prompt: str
    language: str
    country: str | None = None
    region: str | None = None
    sector: str | None = None
    important_assets: list[str] = field(default_factory=list)
    critical_assets: list[str] = field(default_factory=list)
    current_security_operations: str | None = None
    methodology: str | None = None
    specificity: str | None = None
    need: str | None = None
    data_types: list[str] = field(default_factory=list)


def build_retrieval_context(payload: dict[str, Any]) -> RetrievalContext:
    """Build a RetrievalContext from the normalized policy-generation payload."""
    business_context = payload.get("business_context")
    if not isinstance(business_context, dict):
        business_context = {}

    prompt = payload.get("refined_prompt", "")
    important_assets = _split_terms(business_context.get("important_assets"))
    critical_assets = _split_terms(business_context.get("critical_assets"))
    sector = _optional_string(business_context.get("sector"))
    methodology = _optional_string(business_context.get("methodology"))
    need = _optional_string(business_context.get("need"))

    return RetrievalContext(
        context_id=str(payload.get("context_id", "")),
        refined_prompt=prompt,
        language=str(payload.get("language", "")),
        country=_optional_string(business_context.get("country")),
        region=_optional_string(business_context.get("region")),
        sector=sector,
        important_assets=important_assets,
        critical_assets=critical_assets,
        current_security_operations=_optional_string(business_context.get("current_security_operations")),
        methodology=methodology,
        specificity=_optional_string(business_context.get("generic")),
        need=need,
        data_types=_infer_data_types(" ".join([prompt, sector or "", methodology or "", need or ""])),
    )


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _split_terms(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    separators = [",", ";", "\n"]
    terms = [value]
    for separator in separators:
        terms = [part for term in terms for part in term.split(separator)]
    return [term.strip() for term in terms if term.strip()]


def _infer_data_types(text: str) -> list[str]:
    normalized = text.lower()
    data_types = []
    if any(term in normalized for term in ("personal data", "datos personales", "gdpr", "rgpd")):
        data_types.append("personal_data")
    if any(term in normalized for term in ("health", "medical", "patient", "salud", "paciente")):
        data_types.append("health_data")
    if any(term in normalized for term in ("employee", "hr", "payroll", "rrhh", "nomina", "nómina")):
        data_types.append("employee_data")
    if any(term in normalized for term in ("payment", "ecommerce", "commerce", "pago", "comercio")):
        data_types.append("commerce_data")
    return data_types

