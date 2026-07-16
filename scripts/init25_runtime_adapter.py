#!/usr/bin/env python3
"""Fail-closed Docker Agent runtime boundary for INIT-25 shadow execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import suppress
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import time
import tempfile
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


MAX_PROMPT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
RUNTIME_LOCK = (
    Path(__file__).resolve().parents[1] / "agents" / "docker-agent-runtime.lock.json"
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOG_REF_KEYS = {
    "schema", "path", "sha256", "byte_length", "event_count", "redaction"
}
_EXPECTED_PROFILE_BODY = {
    "profile_id": "init25.shadow.sandbox.v1",
    "version": 1,
    "mode": "shadow",
    "authoritative": False,
    "sandbox": {"required": True, "backend": "sbx", "no_kit": True},
    "tools": {
        "allow": [],
        "deny": ["filesystem", "network", "service", "shell"],
    },
    "egress": {"policy": "provider_only_via_sandbox"},
    "environment": {
        "allow": [
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
            "HOME",
            "OPENAI_API_KEY",
            "PATH",
            "SSL_CERT_DIR",
            "SSL_CERT_FILE",
            "TELEMETRY_ENABLED",
        ]
    },
    "deadline": {"required": True, "scope": "global"},
    "rollback": {
        "mode": "automatic",
        "actions": ["terminate_process_group", "preserve_bounded_evidence"],
    },
}


@dataclass(frozen=True)
class RuntimeAdapterResult:
    stdout: str
    error_code: str | None
    returncode: int
    runtime_invocation: dict[str, Any]


@dataclass(frozen=True)
class _Execution:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error_code: str | None = None


Executor = Callable[..., Any]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_ids(values: Sequence[str], field: str) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field}_invalid")
    result = list(values)
    if len(result) != len(set(result)) or any(
        not isinstance(value, str) or not _IDENTIFIER.fullmatch(value)
        for value in result
    ):
        raise ValueError(f"{field}_invalid")
    return result


def _profile_digest(body: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json(body))


def _load_permission_profile(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("permission_profile_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != set(_EXPECTED_PROFILE_BODY) | {"integrity"}:
        raise ValueError("permission_profile_invalid")
    body = {key: payload[key] for key in _EXPECTED_PROFILE_BODY}
    integrity = payload.get("integrity")
    digest = _profile_digest(body)
    if (
        body != _EXPECTED_PROFILE_BODY
        or not isinstance(integrity, dict)
        or set(integrity) != {"algorithm", "value"}
        or integrity.get("algorithm") != "sha256"
        or integrity.get("value") != digest
    ):
        raise ValueError("permission_profile_invalid")
    return body, digest


def _load_runtime_lock(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("runtime_lock_invalid") from exc
    version = payload.get("version") if isinstance(payload, dict) else None
    commit = payload.get("commit") if isinstance(payload, dict) else None
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"v\d+\.\d+\.\d+", version)
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise ValueError("runtime_lock_invalid")
    return version, commit


def _bounded_error(stderr: str, stdout: str, returncode: int) -> str | None:
    if returncode == 0:
        return None
    hint = (stderr + stdout).lower()
    if "429" in hint or "quota" in hint or "rate limit" in hint:
        return "provider_quota_exceeded"
    if "401" in hint or "unauthorized" in hint or "api key" in hint:
        return "provider_auth_failed"
    return "runtime_failed"


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_process_group(
    command: list[str], *, prompt: str, env: dict[str, str], timeout: float
) -> _Execution:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    assert process.stdin and process.stdout and process.stderr
    streams = selectors.DefaultSelector()
    prompt_bytes = prompt.encode("utf-8")
    offset = 0
    if prompt_bytes:
        os.set_blocking(process.stdin.fileno(), False)
        streams.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    else:
        process.stdin.close()
    streams.register(process.stdout, selectors.EVENT_READ, "stdout")
    streams.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + timeout
    error_code = None

    while streams.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            error_code = "runtime_timeout"
            break
        for key, _ in streams.select(min(remaining, 0.1)):
            if key.data == "stdin":
                try:
                    offset += os.write(
                        key.fileobj.fileno(), prompt_bytes[offset : offset + 65536]
                    )
                except BlockingIOError:
                    continue
                except BrokenPipeError:
                    offset = len(prompt_bytes)
                if offset == len(prompt_bytes):
                    streams.unregister(key.fileobj)
                    key.fileobj.close()
                continue
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                streams.unregister(key.fileobj)
                continue
            target = stdout if key.data == "stdout" else stderr
            if len(stdout) + len(stderr) + len(chunk) > MAX_OUTPUT_BYTES:
                error_code = "runtime_output_exceeded"
                break
            target.extend(chunk)
        if error_code:
            break

    streams.close()
    with suppress(OSError):
        process.stdin.close()
    if error_code:
        _terminate_process_group(process)
        return _Execution(returncode=process.returncode or 1, error_code=error_code)
    returncode = process.wait()
    _terminate_process_group(process)
    decoded_stdout = stdout.decode("utf-8", errors="replace")
    decoded_stderr = stderr.decode("utf-8", errors="replace")
    return _Execution(
        stdout=decoded_stdout,
        stderr=decoded_stderr,
        returncode=returncode,
        error_code=_bounded_error(decoded_stderr, decoded_stdout, returncode),
    )


def _coerce_execution(value: Any) -> _Execution:
    if isinstance(value, _Execution):
        return value
    stdout = getattr(value, "stdout", "") or ""
    stderr = getattr(value, "stderr", "") or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    returncode = int(getattr(value, "returncode", 0))
    if len(stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return _Execution(returncode=1, error_code="runtime_output_exceeded")
    return _Execution(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        error_code=getattr(value, "error_code", None)
        or _bounded_error(stderr, stdout, returncode),
    )


class DockerAgentRuntimeAdapter:
    def __init__(
        self,
        config_path: str | Path,
        permission_profile_path: str | Path,
        output_dir: str | Path,
        executor: Executor | None = None,
    ) -> None:
        self.config_path = Path(config_path).resolve(strict=True)
        self.permission_profile_path = Path(permission_profile_path).resolve(strict=True)
        self.output_dir = Path(output_dir).resolve()
        self.executor = executor
        self._profile, self._profile_sha256 = _load_permission_profile(
            self.permission_profile_path
        )
        self._config_sha256 = _sha256(self.config_path.read_bytes())
        self._expected_runtime_identity = _load_runtime_lock(RUNTIME_LOCK)
        self._runtime_identity_cache: tuple[str, str] | None = None

    def _environment(self, runtime_root: Path) -> dict[str, str]:
        allowed = self._profile["environment"]["allow"]
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env.update(
            {
                "DOCKER_AGENT_AUTO_INSTALL": "false",
                "DOCKER_AGENT_AUTO_UPDATE": "false",
                "HOME": str(runtime_root / "home"),
                "TELEMETRY_ENABLED": "false",
            }
        )
        (runtime_root / "home").mkdir()
        return env

    def _runtime_identity(
        self, env: dict[str, str], timeout: float
    ) -> tuple[str, str] | None:
        if self._runtime_identity_cache is not None:
            return self._runtime_identity_cache
        try:
            result = subprocess.run(
                ["docker", "agent", "version"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=min(10, timeout),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode:
            return None
        version = re.search(r"\bversion\s+(v\d+\.\d+\.\d+)\b", result.stdout)
        commit = re.search(r"^Commit:\s+([0-9a-f]{40})$", result.stdout, re.MULTILINE)
        if not version or not commit:
            return None
        self._runtime_identity_cache = (version.group(1), commit.group(1))
        return self._runtime_identity_cache

    def _write_log_evidence(self, invocation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        logs_dir = self.output_dir / "runtime-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        payload = b"".join(_canonical_json(event) + b"\n" for event in events)
        relative_path = Path("runtime-logs") / f"{invocation_id}.jsonl"
        destination = self.output_dir / relative_path
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        return {
            "schema": "init25.runtime-log-evidence.v1",
            "path": relative_path.as_posix(),
            "sha256": _sha256(payload),
            "byte_length": len(payload),
            "event_count": len(events),
            "redaction": "allowlist_bounded_metadata_only",
        }

    def verify_logs_ref(self, logs_ref: Mapping[str, Any]) -> bool:
        if not isinstance(logs_ref, Mapping) or set(logs_ref) != _LOG_REF_KEYS:
            return False
        path = logs_ref.get("path")
        if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
            return False
        try:
            candidate = (self.output_dir / path).resolve(strict=True)
            logs_root = (self.output_dir / "runtime-logs").resolve(strict=True)
            candidate.relative_to(logs_root)
            payload = candidate.read_bytes()
        except (OSError, ValueError):
            return False
        return (
            logs_ref.get("schema") == "init25.runtime-log-evidence.v1"
            and logs_ref.get("redaction") == "allowlist_bounded_metadata_only"
            and isinstance(logs_ref.get("sha256"), str)
            and bool(_SHA256.fullmatch(logs_ref["sha256"]))
            and logs_ref["sha256"] == _sha256(payload)
            and logs_ref.get("byte_length") == len(payload)
            and logs_ref.get("event_count") == len(payload.splitlines())
        )

    def invoke(
        self,
        agent: str,
        prompt: str,
        correlation_id: str,
        input_artifact_ids: Sequence[str],
        expected_output_artifact_ids: Sequence[str],
        timeout: float,
    ) -> RuntimeAdapterResult:
        if not _AGENT.fullmatch(agent):
            raise ValueError("agent_invalid")
        if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("prompt_invalid")
        if not _IDENTIFIER.fullmatch(correlation_id):
            raise ValueError("correlation_id_invalid")
        inputs = _validate_ids(input_artifact_ids, "input_artifact_ids")
        expected_outputs = _validate_ids(
            expected_output_artifact_ids, "expected_output_artifact_ids"
        )
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_invalid")
        _, current_profile_sha256 = _load_permission_profile(
            self.permission_profile_path
        )
        if current_profile_sha256 != self._profile_sha256:
            raise ValueError("permission_profile_invalid")

        invocation_id = str(uuid4())
        started_at = _utc_now()
        started = time.monotonic()
        deadline = started + timeout
        mode = "dry_run" if self.executor is not None else "shadow"
        command = [
            "docker",
            "agent",
            "run",
            str(self.config_path),
            "--agent",
            agent,
            "--exec",
            "--json",
            "--sandbox",
            "--no-kit",
            "-",
        ]
        runtime_version = "simulated"
        with tempfile.TemporaryDirectory(prefix="init25-runtime-") as temp_dir:
            env = self._environment(Path(temp_dir))
            if self.executor is None and shutil.which("sbx", path=env.get("PATH")) is None:
                execution = _Execution(returncode=126, error_code="sbx_unavailable")
                runtime_version = "unavailable"
            elif self.executor is None:
                remaining = deadline - time.monotonic()
                runtime_identity = (
                    self._runtime_identity(env, remaining)
                    if remaining > 0
                    else None
                )
                runtime_version = runtime_identity[0] if runtime_identity else "unavailable"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    execution = _Execution(returncode=124, error_code="runtime_timeout")
                elif runtime_identity is None:
                    execution = _Execution(
                        returncode=1, error_code="runtime_version_unavailable"
                    )
                elif runtime_identity != self._expected_runtime_identity:
                    execution = _Execution(
                        returncode=1, error_code="runtime_incompatible"
                    )
                else:
                    execution = _run_process_group(
                        command,
                        prompt=prompt,
                        env=env,
                        timeout=remaining,
                    )
            else:
                try:
                    execution = _coerce_execution(
                        self.executor(
                            command,
                            input=prompt,
                            env=env,
                            timeout=timeout,
                            max_output_bytes=MAX_OUTPUT_BYTES,
                        )
                    )
                except Exception:
                    execution = _Execution(
                        returncode=1, error_code="simulation_failed"
                    )

        finished_at = _utc_now()
        duration_ms = round((time.monotonic() - started) * 1000)
        exit_status = (
            "simulated"
            if self.executor is not None and execution.error_code is None
            else "completed"
            if execution.error_code is None
            else "timed_out"
            if execution.error_code == "runtime_timeout"
            else "failed"
        )
        events = [
            {
                "sequence": 1,
                "event": "runtime.invocation.started",
                "invocation_id": invocation_id,
                "correlation_id": correlation_id,
                "agent_name": agent,
                "stage": "runtime",
                "result": "started",
            },
            {
                "sequence": 2,
                "event": "runtime.invocation.finished",
                "invocation_id": invocation_id,
                "correlation_id": correlation_id,
                "agent_name": agent,
                "stage": "runtime",
                "result": "completed" if execution.error_code is None else "failed",
                "duration_ms": duration_ms,
                "exit_status": exit_status,
                **({"error_code": execution.error_code} if execution.error_code else {}),
            },
        ]
        logs_ref = self._write_log_evidence(invocation_id, events)
        runtime_invocation = {
            "runtime": "docker-agent-simulated" if self.executor is not None else "docker-agent",
            "runtime_version": runtime_version,
            "agent_config_ref": {
                "name": self.config_path.name,
                "sha256": self._config_sha256,
            },
            "agent_name": agent,
            "mode": mode,
            "input_artifact_ids": inputs,
            "output_artifact_ids": [],
            "permission_profile": {
                "id": self._profile["profile_id"],
                "sha256": self._profile_sha256,
            },
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_status": exit_status,
            "logs_ref": logs_ref,
        }
        return RuntimeAdapterResult(
            stdout=execution.stdout,
            error_code=execution.error_code,
            returncode=execution.returncode,
            runtime_invocation=runtime_invocation,
        )
