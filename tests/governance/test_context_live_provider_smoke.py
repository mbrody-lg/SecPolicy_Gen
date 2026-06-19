import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_context_live_provider_smoke_artifact import validate  # noqa: E402


def test_context_live_provider_smoke_requires_explicit_opt_in():
    result = subprocess.run(
        ["bash", "scripts/run_context_live_provider_smoke.sh"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "RUN_REAL_PROVIDER_TESTS=1 is required" in result.stderr


def test_context_live_provider_smoke_artifact_validator_accepts_bounded_metadata():
    validate({
        "artifact": "context-agent-live-provider-smoke",
        "version": "1.0",
        "generated_at": "2026-06-18T00:00:00+00:00",
        "redaction": "hashes_and_bounded_metadata_only",
        "provider": {"api_mode": "chat_completions", "model_configured": True},
        "case": {
            "id": "healthcare_live_provider_smoke",
            "input_hash": "a" * 64,
            "security_context_hash": "b" * 64,
            "retrieval_collection_families": ["legal_norms"],
            "missing_information_count": 0,
        },
        "phases": [
            {
                "phase": "context_building",
                "success": True,
                "schema_hash": "c" * 64,
                "top_level_keys": ["summary"],
            },
            {
                "phase": "context_planning",
                "success": True,
                "schema_hash": "d" * 64,
                "top_level_keys": ["tasks"],
            },
            {
                "phase": "context_task_result",
                "success": True,
                "schema_hash": "e" * 64,
                "top_level_keys": ["findings"],
            },
        ],
    })


def test_context_live_provider_smoke_artifact_validator_rejects_provider_payload():
    with pytest.raises(SystemExit, match="forbidden key"):
        validate({
            "artifact": "context-agent-live-provider-smoke",
            "version": "1.0",
            "redaction": "hashes_and_bounded_metadata_only",
            "phases": [
                {
                    "phase": "context_building",
                    "success": True,
                    "schema_hash": "c" * 64,
                    "top_level_keys": [],
                    "provider_payload": {"secret": "value"},
                },
                {
                    "phase": "context_planning",
                    "success": True,
                    "schema_hash": "d" * 64,
                    "top_level_keys": [],
                },
                {
                    "phase": "context_task_result",
                    "success": True,
                    "schema_hash": "e" * 64,
                    "top_level_keys": [],
                },
            ],
        })
