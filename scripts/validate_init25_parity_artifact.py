#!/usr/bin/env python3
"""Validate the INIT-25 Docker Agent/cagent parity report contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


VALID_RECOMMENDATIONS = {"continue", "narrow", "pause"}
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


def _require_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        _fail(f"{field} must be an object")
    return value


def _require_list(payload: dict[str, Any], field: str) -> list[Any]:
    value = payload.get(field)
    if not isinstance(value, list):
        _fail(f"{field} must be a list")
    return value


def validate(payload: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        _fail(f"missing required fields: {', '.join(sorted(missing))}")

    if not isinstance(payload.get("case_id"), str) or not payload["case_id"].strip():
        _fail("case_id must be a non-empty string")
    if not isinstance(payload.get("contract_compatible"), bool):
        _fail("contract_compatible must be a boolean")

    _require_list(payload, "artifact_differences")
    _require_list(payload, "runtime_errors")
    _require_list(payload, "security_findings")
    _require_object(payload, "evidence_coverage")
    _require_object(payload, "validation_difference")
    _require_object(payload, "timing")
    _require_object(payload, "observability")

    recommendation = payload.get("recommendation")
    if recommendation not in VALID_RECOMMENDATIONS:
        _fail("recommendation must be continue, narrow, or pause")

    if payload["contract_compatible"] and payload["runtime_errors"]:
        _fail("contract-compatible reports must not contain runtime_errors")

    if _contains_sensitive_key(payload):
        _fail("artifact contains sensitive or raw runtime payload keys")


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
