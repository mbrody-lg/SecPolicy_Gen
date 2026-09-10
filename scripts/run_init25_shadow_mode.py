#!/usr/bin/env python3
"""Run the bounded INIT-25 Docker Agent flow against a contractual baseline."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_init25_parity_report import build_report
from scripts.init25_runtime_adapter import DockerAgentRuntimeAdapter
from scripts.run_init25_contract_dry_run import run_case
from scripts.validate_init25_parity_artifact import validate_no_sensitive_fields


CASE_FILE = ROOT / "tests" / "fixtures" / "init25" / "dry_run_cases.json"
LEAF_AGENTS = (
    "context_agent",
    "regulatory_rag_agent",
    "policy_agent",
    "validator_agent",
)
OWNED_ARTIFACTS = {
    "context_agent": {"context_agent.policy_handoff.v1"},
    "regulatory_rag_agent": {
        "rag.retrieval_context",
        "rag.retrieval_plan",
        "rag.retrieval_evidence",
    },
    "policy_agent": {"policy_agent.policy_draft"},
    "validator_agent": {
        "validator.validation_payload",
        "validator.validation_decision",
    },
}
MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 120.0
CONFIG_FILE = ROOT / "agents" / "secpolicy_contract_dry_run.yaml"
PERMISSION_PROFILE = ROOT / "agents" / "init25_shadow_permission_profile.json"
_FIELD = re.compile(r"^[a-z][a-z0-9_.]*$")
_CODE = re.compile(r"^[a-z][a-z0-9_]*$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


Executor = Callable[..., Any]


def _failure_code(text: str) -> str:
    lowered = text.lower()
    if "429" in lowered or "quota" in lowered or "rate limit" in lowered or "rate_limit" in lowered:
        return "provider_quota_exceeded"
    if (
        "401" in lowered
        or "unauthorized" in lowered
        or "authentication" in lowered
        or "api key" in lowered
        or "api_key" in lowered
    ):
        return "provider_auth_failed"
    return "runtime_failed"


def _command(agent: str) -> list[str]:
    return [
        "docker",
        "agent",
        "run",
        str(CONFIG_FILE),
        "--agent",
        agent,
        "--exec",
        "--json",
        "--sandbox",
        "--no-kit",
        "-",
    ]


def parse_stage_output(stdout: str, expected_agent: str) -> dict[str, Any]:
    """Extract only the structured assistant output from Docker Agent NDJSON."""
    fragments: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_ndjson") from exc
        if (
            isinstance(event, dict)
            and event.get("type") == "agent_choice"
            and event.get("agent_name") == expected_agent
        ):
            content = event.get("content")
            if not isinstance(content, str):
                raise ValueError("invalid_stage_output")
            fragments.append(content)
    try:
        stage = json.loads("".join(fragments))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_stage_output") from exc
    if not isinstance(stage, dict):
        raise ValueError("invalid_stage_output")
    return stage


def load_case(path: Path, case_id: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise SystemExit("INIT-25 shadow case error: case file must contain a cases list")
    for case in cases:
        if isinstance(case, dict) and case.get("case_id") == case_id:
            return case
    raise SystemExit(f"INIT-25 shadow case error: unknown case_id {case_id}")


def _runtime_error(code: str, stage: str) -> dict[str, str]:
    return {"error_code": code, "stage": stage}


def _bounded_objects(value: Any, *, code_key: str) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    bounded = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {code_key, "stage"}:
            return None
        code, stage = item.get(code_key), item.get("stage")
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            return None
        if not isinstance(stage, str) or not _FIELD.fullmatch(stage):
            return None
        bounded.append({code_key: code, "stage": stage})
    return bounded


def _validate_stage(
    agent: str,
    stage: dict[str, Any],
    case_id: str,
    correlation_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    allowed = {"case_id", "correlation_id", "status", "artifacts", "runtime_errors", "security_findings"}
    if agent == "regulatory_rag_agent":
        allowed.add("covered_evidence_families")
    if agent == "validator_agent":
        allowed.add("validation_status")
    if set(stage) != allowed or stage.get("case_id") != case_id or stage.get("correlation_id") != correlation_id:
        return None, "stage_identity_invalid"
    if stage.get("status") not in {"completed", "blocked", "failed"}:
        return None, "stage_status_invalid"

    artifacts = stage.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != OWNED_ARTIFACTS[agent]:
        return None, "artifact_ownership_invalid"
    for fields in artifacts.values():
        if (
            not isinstance(fields, list)
            or any(not isinstance(field, str) or not _FIELD.fullmatch(field) for field in fields)
            or len(fields) != len(set(fields))
        ):
            return None, "artifact_fields_invalid"

    runtime_errors = _bounded_objects(stage.get("runtime_errors"), code_key="error_code")
    findings = _bounded_objects(stage.get("security_findings"), code_key="finding_code")
    if runtime_errors is None or findings is None:
        return None, "stage_metadata_invalid"

    bounded = {
        "status": stage["status"],
        "artifacts": {name: sorted(fields) for name, fields in artifacts.items()},
        "runtime_errors": runtime_errors,
        "security_findings": findings,
    }
    if agent == "regulatory_rag_agent":
        families = stage.get("covered_evidence_families")
        if not isinstance(families, list) or any(not isinstance(item, str) or not _FIELD.fullmatch(item) for item in families):
            return None, "evidence_coverage_invalid"
        bounded["covered_evidence_families"] = sorted(set(families))
    if agent == "validator_agent":
        if stage.get("validation_status") not in {"accepted", "review", "rejected", "not_run"}:
            return None, "validation_status_invalid"
        bounded["validation_status"] = stage["validation_status"]
    return bounded, None


def _simulated_stage(agent: str, case: dict[str, Any], authoritative: dict[str, Any]) -> dict[str, Any]:
    artifacts = authoritative["artifacts"]
    stage = {
        "case_id": case["case_id"],
        "correlation_id": authoritative["correlation_id"],
        "status": "completed",
        "artifacts": {name: artifacts[name] for name in OWNED_ARTIFACTS[agent] if name in artifacts},
        "runtime_errors": [],
        "security_findings": [],
    }
    if agent == "context_agent" and case["input"].get("context_ready_for_policy") is not True:
        stage["status"] = "blocked"
    if agent == "regulatory_rag_agent":
        stage["covered_evidence_families"] = authoritative["covered_evidence_families"]
    if agent == "validator_agent":
        stage["validation_status"] = authoritative["validation_status"]
    return stage


def _coerce_execution(result: Any, expected_agent: str) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(result, dict):
        return result, None
    if isinstance(result, str):
        stdout, returncode, stderr = result, 0, ""
        error_code = None
    else:
        stdout = getattr(result, "stdout", "") or ""
        returncode = getattr(result, "returncode", 0)
        stderr = getattr(result, "stderr", "") or ""
        error_code = getattr(result, "error_code", None)
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if error_code:
        return None, str(error_code)
    if returncode:
        return None, _failure_code(str(stderr) + str(stdout))
    if len(str(stdout).encode("utf-8")) > MAX_OUTPUT_BYTES:
        return None, "runtime_failed"
    try:
        return parse_stage_output(str(stdout), expected_agent), None
    except ValueError as exc:
        return None, str(exc)


def _deterministic_authoritative(case: dict[str, Any]) -> dict[str, Any]:
    baseline_started = time.monotonic()
    _, authoritative, _ = run_case(case)
    authoritative = dict(authoritative)
    authoritative["baseline_type"] = "deterministic_contract_baseline"
    authoritative["live_service_parity"] = False
    authoritative["required_evidence_families"] = list(
        case["input"]["required_evidence_families"]
    )
    authoritative["duration_ms"] = round(
        (time.monotonic() - baseline_started) * 1000
    )
    return authoritative


def _validate_authoritative_summary(
    authoritative: dict[str, Any], case_id: str
) -> dict[str, Any]:
    validate_no_sensitive_fields(authoritative)
    allowed = {
        "schema_version",
        "case_id",
        "baseline_type",
        "live_service_parity",
        "input_alignment",
        "artifact_evidence",
        "validation_status",
        "required_evidence_families",
        "correlation_id",
        "artifacts",
        "duration_ms",
        "source",
        "runtime_errors",
    }
    if set(authoritative) != allowed:
        raise ValueError("authoritative_fields_invalid")
    if authoritative.get("case_id") != case_id:
        raise ValueError("authoritative_case_id_mismatch")
    if authoritative.get("baseline_type") != "live_authoritative_service_capture":
        raise ValueError("authoritative_baseline_invalid")
    runtime_errors = _bounded_objects(
        authoritative.get("runtime_errors"), code_key="error_code"
    )
    if runtime_errors is None:
        raise ValueError("authoritative_runtime_errors_invalid")
    if authoritative.get("live_service_parity") is not False:
        raise ValueError("authoritative_parity_claim_invalid")
    if (
        authoritative.get("schema_version") != "1.0"
        or authoritative.get("input_alignment") != "unverified"
        or authoritative.get("artifact_evidence")
        != "contract_projection_not_observed"
        or authoritative.get("validation_status")
        not in {"accepted", "review", "rejected"}
        or not isinstance(authoritative.get("duration_ms"), int)
        or authoritative["duration_ms"] < 0
    ):
        raise ValueError("authoritative_contract_invalid")
    correlation_id = authoritative.get("correlation_id")
    if not isinstance(correlation_id, str) or not _IDENTIFIER.fullmatch(correlation_id):
        raise ValueError("authoritative_correlation_invalid")
    families = authoritative.get("required_evidence_families")
    if (
        not isinstance(families, list)
        or any(not isinstance(item, str) or not _FIELD.fullmatch(item) for item in families)
        or len(families) != len(set(families))
    ):
        raise ValueError("authoritative_evidence_invalid")
    artifacts = authoritative.get("artifacts")
    expected_artifacts = set().union(*OWNED_ARTIFACTS.values())
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise ValueError("authoritative_artifacts_invalid")
    for fields in artifacts.values():
        if (
            not isinstance(fields, list)
            or any(not isinstance(field, str) or not _FIELD.fullmatch(field) for field in fields)
            or len(fields) != len(set(fields))
        ):
            raise ValueError("authoritative_artifacts_invalid")
    source = authoritative.get("source")
    if (
        not isinstance(source, dict)
        or set(source) != {"smoke_run_id", "context_id", "mode"}
        or source.get("mode") != "runtime"
        or any(
            not isinstance(source.get(key), str)
            or not _IDENTIFIER.fullmatch(source[key])
            for key in ("smoke_run_id", "context_id")
        )
    ):
        raise ValueError("authoritative_source_invalid")
    return {
        **authoritative,
        "required_evidence_families": list(families),
        "artifacts": {name: list(fields) for name, fields in artifacts.items()},
        "source": dict(source),
        "runtime_errors": runtime_errors,
    }


def run_shadow_mode(
    case: dict[str, Any],
    *,
    mode: str = "live",
    executor: Executor | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    authoritative_summary: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if mode not in {"live", "simulated"}:
        raise ValueError("mode must be live or simulated")
    if executor is not None and mode != "simulated":
        raise ValueError("custom executor requires simulated mode")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")

    case_id = case["case_id"]
    if mode == "live" and authoritative_summary is not None:
        authoritative = _validate_authoritative_summary(authoritative_summary, case_id)
    else:
        authoritative = _deterministic_authoritative(case)
    correlation_id = authoritative["correlation_id"]
    candidate: dict[str, Any] = {
        "execution_mode": mode,
        "validation_status": "not_run",
        "covered_evidence_families": [],
        "correlation_id": correlation_id,
        "artifacts": {},
        "runtime_errors": [],
        "security_findings": [],
        "provider_attempted": False,
        "provider_invoked": False,
    }
    started = time.monotonic()
    deadline = started + timeout
    if mode == "live" and authoritative_summary is None:
        candidate["runtime_errors"].append(
            _runtime_error("authoritative_capture_missing", "authoritative_capture")
        )
    if mode == "live":
        candidate["runtime_errors"].extend(authoritative.get("runtime_errors", []))
        candidate["runtime_invocations"] = []
        candidate["verified_logs_ref_count"] = 0

    credential_available = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if mode == "live" and not credential_available:
        candidate["runtime_errors"].append(_runtime_error("credential_missing", "shadow_runner"))

    adapter = None
    if mode == "live" and credential_available:
        if output_dir is None:
            candidate["runtime_errors"].append(
                _runtime_error("runtime_output_dir_missing", "shadow_runner")
            )
        else:
            adapter = DockerAgentRuntimeAdapter(
                CONFIG_FILE,
                PERMISSION_PROFILE,
                output_dir,
            )
    previous_stages: list[dict[str, Any]] = []

    for agent in LEAF_AGENTS:
        if mode == "live" and adapter is None:
            break
        if mode == "simulated" and executor is None:
            raw_stage: Any = _simulated_stage(agent, case, authoritative)
        else:
            prompt = json.dumps({
                "case_id": case_id,
                "correlation_id": correlation_id,
                "context_ready_for_policy": case["input"].get("context_ready_for_policy") is True,
                "expected_artifact_names": sorted(OWNED_ARTIFACTS[agent]),
                "required_evidence_families": authoritative["required_evidence_families"],
                "previous_stages": previous_stages,
            }, separators=(",", ":"))
            if mode == "live":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    candidate["runtime_errors"].append(
                        _runtime_error("runtime_timeout", agent)
                    )
                    break
                assert adapter is not None
                result = adapter.invoke(
                    agent=agent,
                    prompt=prompt,
                    correlation_id=correlation_id,
                    input_artifact_ids=[f"case:{case_id}", *sorted(candidate["artifacts"])],
                    expected_output_artifact_ids=sorted(OWNED_ARTIFACTS[agent]),
                    timeout=remaining,
                )
                candidate["runtime_invocations"].append(result.runtime_invocation)
                if adapter.verify_logs_ref(result.runtime_invocation["logs_ref"]):
                    candidate["verified_logs_ref_count"] += 1
                else:
                    candidate["runtime_errors"].append(
                        _runtime_error("runtime_logs_unverified", agent)
                    )
                    break
                candidate["provider_attempted"] = result.error_code not in {
                    "sbx_unavailable",
                    "runtime_timeout",
                    "runtime_version_unavailable",
                }
                raw_stage = result
            else:
                try:
                    raw_stage = executor(
                        _command(agent),
                        input=prompt,
                        env={},
                        timeout=timeout,
                        max_output_bytes=MAX_OUTPUT_BYTES,
                    )
                except Exception:
                    raw_stage = type(
                        "SimulationFailure",
                        (),
                        {"stdout": "", "returncode": 1, "error_code": "simulation_failed"},
                    )()

        stage, execution_error = _coerce_execution(raw_stage, agent)
        if execution_error:
            candidate["runtime_errors"].append(_runtime_error(execution_error, agent))
            break
        assert stage is not None
        bounded, validation_error = _validate_stage(agent, stage, case_id, correlation_id)
        if validation_error:
            candidate["runtime_errors"].append(_runtime_error(validation_error, agent))
            break
        assert bounded is not None
        if mode == "live":
            candidate["provider_invoked"] = True
            candidate["runtime_invocations"][-1]["output_artifact_ids"] = sorted(
                bounded["artifacts"]
            )
        candidate["artifacts"].update(bounded["artifacts"])
        candidate["runtime_errors"].extend(bounded["runtime_errors"])
        candidate["security_findings"].extend(bounded["security_findings"])
        if agent == "regulatory_rag_agent":
            candidate["covered_evidence_families"] = bounded["covered_evidence_families"]
        if agent == "validator_agent":
            candidate["validation_status"] = bounded["validation_status"]
        previous_stages.append({"agent": agent, **bounded})
        if bounded["status"] in {"blocked", "failed"}:
            candidate["runtime_errors"].append(
                _runtime_error(f"stage_{bounded['status']}", agent)
            )
            break

    if mode == "simulated":
        candidate["simulation_only"] = True
        candidate["runtime_errors"].append(_runtime_error("simulation_only", "shadow_runner"))
        candidate["provider_attempted"] = False
        candidate["provider_invoked"] = False
    candidate["duration_ms"] = round((time.monotonic() - started) * 1000)
    report = build_report(case_id, authoritative, candidate)
    return authoritative, candidate, report


run_shadow_case = run_shadow_mode


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-file", type=Path, default=CASE_FILE)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("live", "simulated"), default="live")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--authoritative-summary", type=Path)
    args = parser.parse_args()

    authoritative_summary = None
    if args.authoritative_summary:
        authoritative_summary = json.loads(
            args.authoritative_summary.read_text(encoding="utf-8")
        )
        if not isinstance(authoritative_summary, dict):
            raise SystemExit("INIT-25 shadow error: authoritative summary must be an object")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    authoritative, candidate, report = run_shadow_mode(
        load_case(args.case_file, args.case_id),
        mode=args.mode,
        timeout=args.timeout,
        authoritative_summary=authoritative_summary,
        output_dir=args.output_dir,
    )
    _write_json(args.output_dir / "authoritative-summary.json", authoritative)
    _write_json(args.output_dir / "candidate-summary.json", candidate)
    _write_json(args.output_dir / "parity-report.json", report)
    if report["recommendation"] == "pause":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
