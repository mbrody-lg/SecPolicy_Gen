"""Bounded provider enrichment contract for security context analysis."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .security_context import (
    LIST_FIELDS,
    MAX_FACTS,
    SECURITY_CONTEXT_VERSION,
    STRING_FIELDS,
    SecurityContextValidationError,
    validate_security_context,
)

MAX_ENRICHMENT_UPDATES = 20


def merge_provider_enrichment(
    security_context: dict[str, Any],
    enrichment: dict[str, Any],
) -> dict[str, Any]:
    """Merge a provider enrichment payload into a validated security context.

    The provider payload is intentionally bounded: it can only update existing
    contract fields and append provider-sourced facts. It cannot add new schema
    sections or bypass the final contract validator.
    """
    base = validate_security_context(security_context)
    _validate_enrichment_version(enrichment)
    updates = enrichment.get("updates", {})
    if not isinstance(updates, dict):
        raise SecurityContextValidationError(
            "security_context_enrichment_invalid_updates",
            "updates",
            "Enrichment updates must be an object.",
        )

    merged = deepcopy(base)
    update_count = 0
    for section, fields in updates.items():
        if not isinstance(fields, dict):
            raise SecurityContextValidationError(
                "security_context_enrichment_invalid_section",
                str(section),
                "Enrichment section must be an object.",
            )
        for field, value in fields.items():
            update_count += 1
            if update_count > MAX_ENRICHMENT_UPDATES:
                raise SecurityContextValidationError(
                    "security_context_enrichment_too_many_updates",
                    "updates",
                    f"Enrichment can update at most {MAX_ENRICHMENT_UPDATES} fields.",
                )
            _apply_update(merged, str(section), str(field), value)

    provider_facts = _provider_facts(enrichment.get("facts", []))
    merged["analysis"]["facts"] = (
        merged["analysis"].get("facts", []) + provider_facts
    )[:MAX_FACTS]
    return validate_security_context(merged)


def _validate_enrichment_version(enrichment: dict[str, Any]) -> None:
    if not isinstance(enrichment, dict):
        raise SecurityContextValidationError(
            "security_context_enrichment_invalid_type",
            "enrichment",
            "Enrichment payload must be an object.",
        )
    if enrichment.get("version") != SECURITY_CONTEXT_VERSION:
        raise SecurityContextValidationError(
            "security_context_enrichment_version_unsupported",
            "version",
            f"Enrichment version must be {SECURITY_CONTEXT_VERSION}.",
        )


def _apply_update(merged: dict[str, Any], section: str, field: str, value: Any) -> None:
    field_key = (section, field)
    if field_key not in LIST_FIELDS and field_key not in STRING_FIELDS:
        raise SecurityContextValidationError(
            "security_context_enrichment_field_not_allowed",
            f"updates.{section}.{field}",
            "Enrichment field is not allowed.",
        )
    merged[section][field] = value


def _provider_facts(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SecurityContextValidationError(
            "security_context_enrichment_invalid_facts",
            "facts",
            "Enrichment facts must be a list.",
        )

    facts = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SecurityContextValidationError(
                "security_context_enrichment_invalid_fact",
                f"facts.{index}",
                "Enrichment fact must be an object.",
            )
        facts.append(
            {
                "field": str(item.get("field", "")).strip(),
                "source": "provider",
                "value": str(item.get("value", "")).strip(),
            }
        )
    return facts
