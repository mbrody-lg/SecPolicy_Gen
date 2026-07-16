#!/usr/bin/env python3
"""Validate the INIT-25 Docker Agent/cagent parity report contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


VALID_RECOMMENDATIONS = {"continue", "narrow", "pause"}
VALID_SEMANTIC_READINESS = {"not_assessed", "not_ready"}
VALID_CUTOVER_READINESS = {"not_ready"}
VALID_AUTHORITATIVE_EVIDENCE = {"projected", "observed", "unverified"}
VALID_CANDIDATE_EVIDENCE = {"simulated", "live", "unverified"}
SENSITIVE_KEY_PARTS = {
    "api_key",
    "authorization",
    "body",
    "cookie",
    "password",
    "prompt",
    "provider_payload",
    "raw_output",
    "request",
    "response",
    "secret",
    "stderr",
    "stdout",
    "token",
}
REQUIRED_FIELDS = {
    "case_id",
    "contract_compatible",
    "artifact_differences",
    "evidence_coverage",
    "validation_difference",
    "runtime_errors",
    "timing",
    "observability",
    "security_findings",
    "recommendation",
}


def _fail(message: str) -> None:
    raise SystemExit(f"INIT-25 parity artifact contract error: {message}")


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_key(nested):
                return True
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def validate_no_sensitive_fields(value: Any) -> None:
    if _contains_sensitive_key(value):
        _fail("artifact contains sensitive or raw runtime payload keys")


def _require_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        _fail(f"{field} must be an object")
    return value


def _require_string_list(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail(f"{field} must be a list of strings")


def _require_object_list(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        _fail(f"{field} must be a list of objects")


def validate(payload: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        _fail(f"missing required fields: {', '.join(sorted(missing))}")

    if not isinstance(payload.get("case_id"), str) or not payload["case_id"].strip():
        _fail("case_id must be a non-empty string")
    if not isinstance(payload.get("contract_compatible"), bool):
        _fail("contract_compatible must be a boolean")

    _require_object_list(payload, "artifact_differences")
    _require_object_list(payload, "runtime_errors")
    _require_object_list(payload, "security_findings")
    evidence_coverage = _require_object(payload, "evidence_coverage")
    validation_difference = _require_object(payload, "validation_difference")
    timing = _require_object(payload, "timing")
    observability = _require_object(payload, "observability")
    for field in ("required_families", "covered_families", "missing_families"):
        _require_string_list(evidence_coverage, field)
    if not isinstance(validation_difference.get("authoritative_status"), str):
        _fail("validation_difference.authoritative_status must be a string")
    if not isinstance(validation_difference.get("candidate_status"), str):
        _fail("validation_difference.candidate_status must be a string")
    if not isinstance(validation_difference.get("changed"), bool):
        _fail("validation_difference.changed must be a boolean")
    for field in ("authoritative_ms", "candidate_ms"):
        if timing.get(field) is not None and not isinstance(timing[field], (int, float)):
            _fail(f"timing.{field} must be numeric or null")
    if observability.get("correlation_id") is not None and not isinstance(observability["correlation_id"], str):
        _fail("observability.correlation_id must be a string or null")
    for field in ("has_runtime_invocation", "has_logs_ref"):
        if not isinstance(observability.get(field), bool):
            _fail(f"observability.{field} must be a boolean")

    recommendation = payload.get("recommendation")
    if recommendation not in VALID_RECOMMENDATIONS:
        _fail("recommendation must be continue, narrow, or pause")

    assessment = payload.get("assessment")
    if assessment is not None:
        if not isinstance(assessment, dict) or set(assessment) != {
            "contract_recommendation",
            "semantic_readiness",
            "cutover_readiness",
            "evidence_basis",
        }:
            _fail("assessment must contain the required readiness fields")
        if assessment["contract_recommendation"] != recommendation:
            _fail("assessment contract recommendation must match recommendation")
        if assessment["semantic_readiness"] not in VALID_SEMANTIC_READINESS:
            _fail("assessment semantic_readiness is invalid")
        if assessment["cutover_readiness"] not in VALID_CUTOVER_READINESS:
            _fail("assessment cutover_readiness is invalid")
        evidence_basis = assessment["evidence_basis"]
        if not isinstance(evidence_basis, dict) or set(evidence_basis) != {
            "authoritative",
            "candidate",
        }:
            _fail("assessment evidence_basis must contain authoritative and candidate")
        if evidence_basis["authoritative"] not in VALID_AUTHORITATIVE_EVIDENCE:
            _fail("assessment authoritative evidence is invalid")
        if evidence_basis["candidate"] not in VALID_CANDIDATE_EVIDENCE:
            _fail("assessment candidate evidence is invalid")
        evidence_is_live = (
            evidence_basis["authoritative"] == "observed"
            and evidence_basis["candidate"] == "live"
        )
        if not evidence_is_live and assessment["semantic_readiness"] != "not_assessed":
            _fail("semantic readiness requires observed and live evidence")
        if not evidence_is_live and assessment["cutover_readiness"] != "not_ready":
            _fail("cutover readiness requires observed and live evidence")

    expected_missing = sorted(
        set(evidence_coverage["required_families"])
        - set(evidence_coverage["covered_families"])
    )
    if evidence_coverage["missing_families"] != expected_missing:
        _fail("evidence_coverage.missing_families is inconsistent")
    expected_changed = (
        validation_difference["authoritative_status"]
        != validation_difference["candidate_status"]
    )
    if validation_difference["changed"] is not expected_changed:
        _fail("validation_difference.changed is inconsistent")
    expected_compatible = not payload["artifact_differences"] and not payload["runtime_errors"]
    if payload["contract_compatible"] is not expected_compatible:
        _fail("contract_compatible is inconsistent")

    if recommendation == "continue":
        if not payload["contract_compatible"]:
            _fail("continue requires contract_compatible=true")
        if evidence_coverage["missing_families"]:
            _fail("continue requires complete evidence coverage")
        if validation_difference["changed"]:
            _fail("continue requires unchanged validation status")
        if payload["security_findings"]:
            _fail("continue requires no security findings")

    expected_recommendation = "continue"
    if payload["runtime_errors"] or payload["security_findings"]:
        expected_recommendation = "pause"
    elif not payload["contract_compatible"] or expected_missing or expected_changed:
        expected_recommendation = "narrow"
    if recommendation != expected_recommendation:
        _fail(f"recommendation must be {expected_recommendation} for this report")

    validate_no_sensitive_fields(payload)


def main() -> None:
    if len(sys.argv) != 2:
        _fail("usage: validate_init25_parity_artifact.py <artifact.json>")
    path = Path(sys.argv[1])
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        _fail("artifact root must be an object")
    validate(payload)


if __name__ == "__main__":
    main()
