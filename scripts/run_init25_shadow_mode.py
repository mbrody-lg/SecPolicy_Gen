#!/usr/bin/env python3
"""Run the bounded INIT-25 Docker Agent flow against a contractual baseline."""

from __future__ import annotations

import argparse
from contextlib import suppress
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_init25_parity_report import build_report
from scripts.run_init25_contract_dry_run import run_case


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
_FIELD = re.compile(r"^[a-z][a-z0-9_.]*$")
_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str = ""
    returncode: int = 0
    error_code: str | None = None


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


def execute_subprocess(
    command: list[str],
    *,
    input: str,
    env: dict[str, str],
    timeout: float,
    max_output_bytes: int,
) -> ExecutionResult:
    """Execute a command while bounding captured stdout and discarding stderr."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert process.stdin and process.stdout and process.stderr

    streams = selectors.DefaultSelector()
    input_bytes = input.encode("utf-8")
    input_offset = 0
    if input_bytes:
        os.set_blocking(process.stdin.fileno(), False)
        streams.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    else:
        process.stdin.close()
    streams.register(process.stdout, selectors.EVENT_READ, "stdout")
    streams.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    stderr_hint = bytearray()
    deadline = time.monotonic() + timeout
    error_code: str | None = None

    while streams.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            error_code = "runtime_timeout"
            process.kill()
            break
        for key, _ in streams.select(min(remaining, 0.1)):
            if key.data == "stdin":
                try:
                    input_offset += os.write(
                        key.fileobj.fileno(),
                        input_bytes[input_offset : input_offset + 65536],
                    )
                except BlockingIOError:
                    continue
                except BrokenPipeError:
                    input_offset = len(input_bytes)
                if input_offset == len(input_bytes):
                    streams.unregister(key.fileobj)
                    key.fileobj.close()
                continue
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                streams.unregister(key.fileobj)
                continue
            if key.data == "stdout":
                if len(stdout) + len(chunk) > max_output_bytes:
                    error_code = "runtime_failed"
                    process.kill()
                    break
                stdout.extend(chunk)
            elif len(stderr_hint) < 65536:
                stderr_hint.extend(chunk[: 65536 - len(stderr_hint)])
        if error_code:
            break

    streams.close()
    with suppress(OSError):
        process.stdin.close()
    if error_code:
        process.wait()
        return ExecutionResult(returncode=process.returncode or 1, error_code=error_code)

    returncode = process.wait()
    decoded = stdout.decode("utf-8", errors="replace")
    if returncode:
        hint = stderr_hint.decode("utf-8", errors="replace") + decoded
        return ExecutionResult(returncode=returncode, error_code=_failure_code(hint))
    return ExecutionResult(stdout=decoded)


def detect_runtime_version() -> str:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT"}
    }
    result = execute_subprocess(
        ["docker", "agent", "version"],
        input="",
        env=env,
        timeout=10.0,
        max_output_bytes=4096,
    )
    match = re.search(r"\bversion\s+(v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)\b", result.stdout)
    if result.error_code or not match:
        raise RuntimeError("runtime_version_unavailable")
    return match.group(1)


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


def _environment(root: Path) -> dict[str, str]:
    allowed = {"PATH", "DOCKER_HOST", "DOCKER_CONTEXT", "SSL_CERT_FILE", "SSL_CERT_DIR", "OPENAI_API_KEY"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({
        "HOME": str(root / "home"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "TELEMETRY_ENABLED": "false",
    })
    return env


def _command(agent: str) -> list[str]:
    return [
        "docker", "agent", "run", str(ROOT / "agents" / "secpolicy_contract_dry_run.yaml"),
        "--agent", agent, "--exec", "--json", "-",
    ]


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


def run_shadow_mode(
    case: dict[str, Any],
    *,
    mode: str = "live",
    executor: Executor | None = None,
    version_detector: Callable[[], str] = detect_runtime_version,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if mode not in {"live", "simulated"}:
        raise ValueError("mode must be live or simulated")
    if executor is not None and mode != "simulated":
        raise ValueError("custom executor requires simulated mode")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")

    baseline_started = time.monotonic()
    _, authoritative, _ = run_case(case)
    authoritative = dict(authoritative)
    authoritative["baseline_type"] = "deterministic_contract_baseline"
    authoritative["live_service_parity"] = False
    authoritative["required_evidence_families"] = list(case["input"]["required_evidence_families"])
    authoritative["duration_ms"] = round((time.monotonic() - baseline_started) * 1000)

    case_id = case["case_id"]
    correlation_id = authoritative["correlation_id"]
    candidate: dict[str, Any] = {
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
    runtime_ready = mode != "live"
    if mode == "live":
        try:
            runtime_version = version_detector()
            runtime_ready = True
        except Exception:
            runtime_version = "unknown"
            candidate["runtime_errors"].append(_runtime_error("runtime_version_unavailable", "shadow_runner"))
        candidate["runtime_invocation"] = {
            "mode": "shadow",
            "runtime": "docker-agent",
            "runtime_version": runtime_version,
        }

    credential_available = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if mode == "live" and not credential_available:
        candidate["runtime_errors"].append(_runtime_error("credential_missing", "shadow_runner"))

    with tempfile.TemporaryDirectory(prefix="init25-shadow-") as temp_dir:
        temp_root = Path(temp_dir)
        for directory in ("home", "cache", "config", "data"):
            (temp_root / directory).mkdir()
        env = _environment(temp_root)
        previous_stages: list[dict[str, Any]] = []

        for agent in LEAF_AGENTS:
            if mode == "live" and (not credential_available or not runtime_ready):
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
                candidate["provider_attempted"] = mode == "live"
                try:
                    raw_stage = (executor or execute_subprocess)(
                        _command(agent),
                        input=prompt,
                        env=env,
                        timeout=timeout,
                        max_output_bytes=MAX_OUTPUT_BYTES,
                    )
                except (subprocess.TimeoutExpired, TimeoutError):
                    raw_stage = ExecutionResult(error_code="runtime_timeout", returncode=1)
                except Exception:
                    raw_stage = ExecutionResult(error_code="runtime_failed", returncode=1)

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
            candidate["artifacts"].update(bounded["artifacts"])
            candidate["runtime_errors"].extend(bounded["runtime_errors"])
            candidate["security_findings"].extend(bounded["security_findings"])
            if agent == "regulatory_rag_agent":
                candidate["covered_evidence_families"] = bounded["covered_evidence_families"]
            if agent == "validator_agent":
                candidate["validation_status"] = bounded["validation_status"]
            previous_stages.append({"agent": agent, **bounded})
            if bounded["status"] in {"blocked", "failed"}:
                candidate["runtime_errors"].append(_runtime_error(f"stage_{bounded['status']}", agent))
                break

    if mode == "simulated":
        candidate["simulation_only"] = True
        candidate["runtime_errors"].append(_runtime_error("simulation_only", "shadow_runner"))
        candidate["provider_attempted"] = False
        candidate["provider_invoked"] = False
        candidate.pop("runtime_invocation", None)
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
    args = parser.parse_args()

    authoritative, candidate, report = run_shadow_mode(
        load_case(args.case_file, args.case_id),
        mode=args.mode,
        timeout=args.timeout,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "authoritative-summary.json", authoritative)
    _write_json(args.output_dir / "candidate-summary.json", candidate)
    _write_json(args.output_dir / "parity-report.json", report)
    if report["recommendation"] == "pause":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
