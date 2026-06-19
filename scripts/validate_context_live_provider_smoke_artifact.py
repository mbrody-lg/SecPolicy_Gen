"""Validate the Context Agent live-provider smoke artifact contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path


HEX_DIGITS = set("0123456789abcdef")
FORBIDDEN_KEYS = {
    "prompt",
    "messages",
    "raw_text",
    "raw_output",
    "response",
    "provider_payload",
    "openai_api_key",
    "api_key",
    "secret",
}


def _fail(message: str) -> None:
    raise SystemExit(f"context live-provider smoke artifact error: {message}")


def _walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_KEYS:
                _fail(f"forbidden key present: {key}")
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    else:
        yield value


def validate(payload: dict) -> None:
    if payload.get("artifact") != "context-agent-live-provider-smoke":
        _fail("unexpected artifact name")
    if payload.get("version") != "1.0":
        _fail("unsupported version")
    if payload.get("redaction") != "hashes_and_bounded_metadata_only":
        _fail("redaction marker missing")

    phases = payload.get("phases")
    if not isinstance(phases, list) or len(phases) != 3:
        _fail("expected exactly three phase summaries")
    for phase in phases:
        if not isinstance(phase, dict):
            _fail("phase summary must be an object")
        if phase.get("success") is not True:
            _fail("phase did not report success")
        schema_hash = phase.get("schema_hash")
        if (
            not isinstance(schema_hash, str)
            or len(schema_hash) != 64
            or any(character not in HEX_DIGITS for character in schema_hash.lower())
        ):
            _fail("phase schema_hash must be sha256 hex")
        if not isinstance(phase.get("top_level_keys"), list):
            _fail("phase top_level_keys must be a list")

    for scalar in _walk(payload):
        if isinstance(scalar, str) and len(scalar) > 512:
            _fail("artifact string values must remain bounded")


def main() -> None:
    if len(sys.argv) != 2:
        _fail("usage: validate_context_live_provider_smoke_artifact.py <artifact.json>")
    path = Path(sys.argv[1])
    if not path.exists():
        _fail(f"artifact not found: {path}")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        _fail("artifact root must be an object")
    validate(payload)


if __name__ == "__main__":
    main()
