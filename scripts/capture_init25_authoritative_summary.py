#!/usr/bin/env python3
"""Project a passed runtime smoke artifact into a bounded INIT-25 summary."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_init25_contract_dry_run import ARTIFACT_FIELDS
from scripts.validate_init25_parity_artifact import validate_no_sensitive_fields
from scripts.validate_smoke_artifact import validate as validate_smoke_artifact


VALIDATION_STATUSES = {"accepted", "review", "rejected"}
CORRELATION_FIELDS = (
    "requested_correlation_id",
    "generate_response_correlation_id",
    "header_correlation_id",
    "document_correlation_id",
)


def _fail(message: str) -> None:
    raise SystemExit(f"INIT-25 authoritative capture error: {message}")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot load {label}: {exc}")
    if not isinstance(payload, dict):
        _fail(f"{label} root must be an object")
    return payload


def _without_smoke_contract_exceptions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_smoke_contract_exceptions(nested)
            for key, nested in value.items()
            if key not in {"generate_response_correlation_id", "requested_correlation_id"}
        }
    if isinstance(value, list):
        return [_without_smoke_contract_exceptions(item) for item in value]
    return value


def _select_case(payload: dict[str, Any], case_id: str) -> dict[str, Any]:
    cases = payload.get("cases")
    if not isinstance(cases, list):
        _fail("case file must contain a cases list")
    matches = [case for case in cases if isinstance(case, dict) and case.get("case_id") == case_id]
    if len(matches) != 1:
        _fail(f"case_id {case_id} must match exactly one case")
    validate_no_sensitive_fields(matches[0])
    return matches[0]


def _select_context(payload: dict[str, Any], context_id: str) -> dict[str, Any]:
    contexts = payload.get("contexts")
    if not isinstance(contexts, list):
        _fail("smoke artifact contexts must be a list")
    matches = [
        context
        for context in contexts
        if isinstance(context, dict) and context.get("context_id") == context_id
    ]
    if len(matches) != 1:
        _fail(f"context_id {context_id} must match exactly one context")
    return matches[0]


def _duration_ms(run: dict[str, Any]) -> int:
    try:
        started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        _fail("run timestamps must be valid ISO-8601 values")
    duration = round((finished - started).total_seconds() * 1000)
    if duration < 0:
        _fail("run.finished_at must not precede run.started_at")
    return duration


def _required_evidence_families(case: dict[str, Any]) -> list[str]:
    source = case.get("input")
    families = source.get("required_evidence_families") if isinstance(source, dict) else None
    if (
        not isinstance(families, list)
        or not families
        or any(not isinstance(item, str) or not item.strip() for item in families)
    ):
        _fail("case input.required_evidence_families must be a non-empty string list")
    return sorted(set(item.strip() for item in families))


def _validate_context(context: dict[str, Any]) -> tuple[str, str]:
    status = context.get("last_status")
    if status not in VALIDATION_STATUSES:
        _fail("context last_status must be accepted, review, or rejected")
    if context.get("failure_reasons") != []:
        _fail("selected context must not contain failure reasons")

    observability = context.get("observability")
    if not isinstance(observability, dict):
        _fail("selected context observability must be an object")
    pipeline_job = observability.get("pipeline_job")
    if not isinstance(pipeline_job, dict):
        _fail("selected context pipeline_job must be an object")
    if pipeline_job.get("job_status") != "completed" or pipeline_job.get("job_stage") != "completed":
        _fail("selected context pipeline job must be completed")
    if observability.get("pipeline_status") != "completed":
        _fail("selected context diagnostics must be completed")
    if observability.get("has_policy_hop") is not True:
        _fail("selected context is missing the policy hop")
    if observability.get("has_validator_hop") is not True:
        _fail("selected context is missing the validator hop")

    correlations = [observability.get(field) for field in CORRELATION_FIELDS]
    correlations.append(pipeline_job.get("job_correlation_id"))
    if any(not isinstance(value, str) or not value.strip() for value in correlations):
        _fail("selected context correlation ids must be non-empty strings")
    if len(set(correlations)) != 1:
        _fail("selected context correlation ids are inconsistent")
    return status, correlations[0]


def build_summary(
    smoke_artifact: dict[str, Any],
    case_file: dict[str, Any],
    case_id: str,
    context_id: str,
) -> dict[str, Any]:
    validate_smoke_artifact(smoke_artifact)
    validate_no_sensitive_fields(_without_smoke_contract_exceptions(smoke_artifact))

    run = smoke_artifact["run"]
    if run.get("status") != "passed":
        _fail("smoke run must be passed")
    if run.get("mode") != "runtime":
        _fail("smoke run mode must be runtime")

    case = _select_case(case_file, case_id)
    context = _select_context(smoke_artifact, context_id)
    validation_status, correlation_id = _validate_context(context)
    summary = {
        "schema_version": "1.0",
        "case_id": case_id,
        "baseline_type": "live_authoritative_service_capture",
        "live_service_parity": False,
        "input_alignment": "unverified",
        "artifact_evidence": "contract_projection_not_observed",
        "validation_status": validation_status,
        "required_evidence_families": _required_evidence_families(case),
        "correlation_id": correlation_id,
        "artifacts": {
            name: sorted(fields)
            for name, fields in sorted(ARTIFACT_FIELDS.items())
        },
        "duration_ms": _duration_ms(run),
        "source": {
            "smoke_run_id": run["id"],
            "context_id": context_id,
            "mode": run["mode"],
        },
        "runtime_errors": [
            {"error_code": "authoritative_input_unverified", "stage": "authoritative_capture"},
            {"error_code": "authoritative_artifacts_projected", "stage": "authoritative_capture"},
        ],
    }
    validate_no_sensitive_fields(summary)
    return summary


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-artifact", required=True, type=Path)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--context-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    summary = build_summary(
        _load_object(args.smoke_artifact, "smoke artifact"),
        _load_object(args.case_file, "case file"),
        args.case_id,
        args.context_id,
    )
    _write_json(args.output, summary)


if __name__ == "__main__":
    main()
