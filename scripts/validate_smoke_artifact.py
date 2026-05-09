#!/usr/bin/env python3
"""Validate the functional smoke observability artifact contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path


SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "stderr",
    "stdout",
    "token",
}


def _fail(message: str) -> None:
    raise SystemExit(f"smoke artifact contract error: {message}")


def _contains_sensitive_key(value) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(sensitive in normalized for sensitive in SENSITIVE_KEYS):
                return True
            if _contains_sensitive_key(nested):
                return True
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def validate(payload: dict) -> None:
    if payload.get("schema_version") != "1.0":
        _fail("schema_version must be 1.0")

    run = payload.get("run")
    if not isinstance(run, dict):
        _fail("run must be an object")
    if run.get("status") not in {"passed", "failed"}:
        _fail("run.status must be passed or failed")
    for field in ("id", "started_at", "finished_at", "mode", "golden_dir"):
        if not run.get(field):
            _fail(f"run.{field} is required")

    contexts = payload.get("contexts")
    if not isinstance(contexts, list):
        _fail("contexts must be a list")

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        _fail("summary must be an object")
    if summary.get("total_contexts") != len(contexts):
        _fail("summary.total_contexts must equal len(contexts)")

    failures = payload.get("failures")
    if not isinstance(failures, list):
        _fail("failures must be a list")
    if run["status"] == "passed" and failures:
        _fail("passed run must not contain failures")
    if run["status"] == "failed" and not failures:
        _fail("failed run must contain at least one failure")

    service_checks = payload.get("service_checks")
    if not isinstance(service_checks, dict):
        _fail("service_checks must be an object")
    for service_name, checks in service_checks.items():
        if not isinstance(checks, dict):
            _fail(f"service_checks.{service_name} must be an object")
        ready = checks.get("ready")
        if run["status"] == "passed" and isinstance(ready, dict):
            if ready.get("status_code") != 200 or ready.get("payload_status") != "ready":
                _fail(f"{service_name}.ready must be ready in passed runs")

    if _contains_sensitive_key(payload):
        _fail("artifact contains sensitive output-like keys")


def main() -> None:
    if len(sys.argv) != 2:
        _fail("usage: validate_smoke_artifact.py <artifact.json>")
    path = Path(sys.argv[1])
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        _fail("artifact root must be an object")
    validate(payload)


if __name__ == "__main__":
    main()
