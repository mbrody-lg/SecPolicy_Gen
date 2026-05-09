"""Tests for context-agent structured logging helpers."""

import json

from app import observability


def test_build_log_event_includes_contract_fields(app_context):
    payload = json.loads(
        observability.build_log_event(
            event="context.test.completed",
            stage="test_stage",
            correlation_id="corr-1",
            context_id="ctx-1",
            route="/ready",
            method="GET",
            status_code=200,
            result="success",
            error_code=None,
        )
    )

    for field in observability.REQUIRED_LOG_FIELDS:
        assert field in payload

    assert payload["service"] == observability.SERVICE_NAME
    assert payload["event"] == "context.test.completed"
    assert payload["stage"] == "test_stage"
    assert payload["correlation_id"] == "corr-1"
    assert payload["context_id"] == "ctx-1"
    assert payload["route"] == "/ready"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert payload["result"] == "success"
    assert "error_code" not in payload


def test_log_contract_documents_expected_optional_fields():
    assert "result" in observability.OPTIONAL_LOG_FIELDS
    assert "duration_ms" in observability.NUMERIC_LOG_FIELDS
