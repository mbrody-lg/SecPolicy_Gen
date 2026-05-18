"""Adapters from Context Agent security context to downstream agent contracts."""

from __future__ import annotations

from typing import Any

from .security_context import validate_security_context


def security_context_to_business_context(security_context: dict[str, Any]) -> dict[str, Any]:
    """Flatten `security_context` into Policy Agent's current `business_context`.

    Policy Agent currently expects a shallow object. Keep this adapter explicit
    until INIT-08 formalizes the cross-agent contract.
    """
    context = validate_security_context(security_context)
    profile = context["profile"]
    assets = context["information_assets"]
    compliance = context["compliance"]
    posture = context["security_posture"]
    intent = context["policy_intent"]

    return {
        "country": _first(profile["operating_countries"]),
        "region": profile["region"],
        "sector": profile["sector"],
        "important_assets": assets["important_assets"],
        "critical_assets": assets["critical_assets"],
        "current_security_operations": _join_terms(posture["current_controls"]),
        "methodology": _join_terms(compliance["methodologies"] or compliance["regulatory_hints"]),
        "generic": intent["specificity"],
        "need": intent["need"],
        "data_types": assets["data_categories"],
        "retrieval_collection_families": context["retrieval_hints"]["collection_families"],
    }


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _join_terms(values: list[str]) -> str | None:
    return ", ".join(values) if values else None
