from datetime import datetime, timezone

import pytest
from flask import g

from app import mongo
from app.services import logic


def test_get_health_status_returns_lightweight_payload():
    assert logic.get_health_status() == {
        "status": "ok",
        "service": "policy-agent",
    }


def test_get_readiness_status_returns_ready_when_dependencies_are_available(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setenv("CHROMA_HOST", "chroma")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "config_only")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["config"]["status"] == "ok"
    assert payload["checks"]["mongo"]["status"] == "ok"
    assert payload["checks"]["chroma"] == {
        "status": "configured",
        "mode": "config_only",
        "collection_count": 1,
    }


def test_get_readiness_status_reports_controlled_failure(app, monkeypatch):
    class FailingAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            raise RuntimeError("mongo unavailable")

    class FailingMongoClient:
        admin = FailingAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FailingMongoClient())
    monkeypatch.setenv("CHROMA_PORT", "not-a-number")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "config_only")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["config"]["status"] == "ok"
    assert payload["checks"]["mongo"]["reason"] == "ping_failed"
    assert payload["checks"]["chroma"]["status"] == "error"
    assert payload["checks"]["chroma"]["mode"] == "config_only"
    assert "details" not in payload["checks"]["mongo"]
    assert "details" not in payload["checks"]["chroma"]


def test_get_readiness_status_rejects_empty_chroma_host(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setenv("CHROMA_HOST", " ")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "config_only")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["chroma"] == {
        "status": "error",
        "mode": "config_only",
        "reason": "invalid_configuration",
    }


def test_get_readiness_status_can_run_live_chroma_check(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    class FakeChromaClient:
        def heartbeat(self):
            return 1

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())
    monkeypatch.setenv("CHROMA_HOST", "chroma")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "live")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["chroma"] == {
        "status": "ok",
        "mode": "live",
        "collection_count": 1,
    }


def test_get_readiness_status_rejects_invalid_chroma_readiness_mode(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setenv("CHROMA_HOST", "chroma")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "unexpected")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["chroma"] == {
        "status": "error",
        "mode": "config_only",
        "reason": "invalid_configuration",
    }


def test_get_readiness_status_reads_yaml_style_chroma_vector_entry(app, monkeypatch):
    class FakeAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            return {"ok": 1}

    class FakeMongoClient:
        admin = FakeAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": "Chroma Vector Database",
                            "collection": [
                                "legal_norms",
                                "sector_norms",
                                "security_frameworks",
                                "risk_methodologies",
                                "implementation_guides",
                            ],
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(mongo, "cx", FakeMongoClient())
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "config_only")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 200
    assert payload["checks"]["chroma"] == {
        "status": "configured",
        "mode": "config_only",
        "collection_count": 5,
    }


def test_get_rag_runtime_status_reports_missing_collections(app, monkeypatch):
    class FakeCollection:
        def __init__(self, name):
            self.name = name

    class FakeChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            return [FakeCollection("normativa")]

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["normativa", "guia"],
                                "model": "intfloat/e5-base",
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 503
    assert payload["rag"]["status"] == "requires_refresh"
    assert payload["rag"]["missing_collections"] == ["guia"]


def test_get_rag_runtime_status_treats_mock_policy_as_ready(app, monkeypatch):
    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "mock",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                                "model": "intfloat/e5-base",
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", None)

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["rag"] == {
        "status": "ready",
        "configured_collections": [],
        "available_collections": [],
        "missing_collections": [],
        "embedding_models": [],
        "collection_checks": [],
        "action": "none",
        "refresh_available": False,
        "refresh_job": None,
        "mode": "mock",
    }


def test_get_rag_runtime_status_reports_ready_when_all_collections_exist(app, monkeypatch):
    class FakeCollection:
        def __init__(self, name):
            self.name = name

    class FakeChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            return [FakeCollection("normativa"), "guia"]

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["normativa", "guia"],
                                "model": "intfloat/e5-base",
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())
    monkeypatch.setattr(logic, "is_model_cached", lambda model_id: True)
    monkeypatch.setattr(logic, "has_safetensors_weights", lambda model_id: True)
    monkeypatch.setenv("RAG_VALIDATE_CHROMA", "true")
    monkeypatch.setattr(
        logic,
        "_chroma_collection_runtime_checks",
        lambda config, client, configured_collections: [
            {"collection": name, "status": "ready"} for name in configured_collections
        ],
    )
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", None)

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["rag"]["status"] == "ready"
    assert payload["rag"]["configured_collections"] == ["normativa", "guia"]
    assert payload["rag"]["available_collections"] == ["guia", "normativa"]
    assert payload["rag"]["missing_collections"] == []
    assert payload["rag"]["embedding_models"] == [
        {
            "model": "intfloat/e5-base",
            "revision": None,
            "status": "ready",
        }
    ]
    assert payload["rag"]["collection_checks"] == [
        {"collection": "normativa", "status": "ready"},
        {"collection": "guia", "status": "ready"},
    ]
    assert payload["rag"]["action"] == "none"


def test_get_rag_runtime_status_requires_refresh_when_collection_embedding_is_incompatible(app, monkeypatch):
    class FakeChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            return ["normativa"]

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": "Chroma Vector Database",
                            "collection": ["normativa"],
                            "model": "intfloat/multilingual-e5-base",
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())
    monkeypatch.setattr(logic, "is_model_cached", lambda model_id: True)
    monkeypatch.setattr(logic, "has_safetensors_weights", lambda model_id: True)
    monkeypatch.setenv("RAG_VALIDATE_CHROMA", "true")
    monkeypatch.setattr(
        logic,
        "_chroma_collection_runtime_checks",
        lambda config, client, configured_collections: [
            {
                "collection": "normativa",
                "status": "error",
                "reason": "collection_embedding_incompatible",
            }
        ],
    )
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", None)

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 503
    assert payload["rag"]["status"] == "requires_refresh"
    assert payload["rag"]["collection_checks"] == [
        {
            "collection": "normativa",
            "status": "error",
            "reason": "collection_embedding_incompatible",
        }
    ]
    assert payload["rag"]["action"] == "index_pdfs_to_chroma"


def test_get_rag_runtime_status_skips_deep_chroma_validation_by_default(app, monkeypatch):
    class FakeChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            return ["normativa"]

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": "Chroma Vector Database",
                            "collection": ["normativa"],
                            "model": "intfloat/multilingual-e5-base",
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())
    monkeypatch.setattr(logic, "is_model_cached", lambda model_id: True)
    monkeypatch.setattr(logic, "has_safetensors_weights", lambda model_id: True)
    monkeypatch.setattr(
        logic,
        "_chroma_collection_runtime_checks",
        lambda config, client, configured_collections: pytest.fail("deep Chroma validation is opt-in"),
    )
    monkeypatch.delenv("RAG_VALIDATE_CHROMA", raising=False)
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", None)

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 200
    assert payload["rag"]["status"] == "ready"
    assert payload["rag"]["collection_checks"] == []


def test_get_rag_runtime_status_requires_refresh_when_embedding_model_is_missing(app, monkeypatch):
    class FakeChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            return ["normativa"]

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": "Chroma Vector Database",
                            "collection": ["normativa"],
                            "model": "intfloat/multilingual-e5-base",
                            "revision": "rev-1",
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())
    monkeypatch.setattr(logic, "is_model_cached", lambda model_id: False)

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 503
    assert payload["rag"]["status"] == "requires_refresh"
    assert payload["rag"]["missing_collections"] == []
    assert payload["rag"]["embedding_models"] == [
        {
            "model": "intfloat/multilingual-e5-base",
            "revision": "rev-1",
            "status": "missing",
            "reason": "not_cached",
        }
    ]
    assert payload["rag"]["action"] == "index_pdfs_to_chroma"


def test_get_rag_runtime_status_requires_refresh_while_refresh_job_is_running(app, monkeypatch):
    class FakeChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            return ["normativa"]

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": "Chroma Vector Database",
                            "collection": ["normativa"],
                            "model": "intfloat/multilingual-e5-base",
                            "revision": "rev-1",
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FakeChromaClient())
    monkeypatch.setattr(logic, "is_model_cached", lambda model_id: True)
    monkeypatch.setattr(logic, "has_safetensors_weights", lambda model_id: True)
    monkeypatch.setattr(
        logic,
        "_RAG_REFRESH_JOB",
        {
            "id": "job-1",
            "status": "running",
            "started_at": "2026-05-08T00:00:00+00:00",
        },
    )

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 503
    assert payload["rag"]["status"] == "requires_refresh"
    assert payload["rag"]["action"] == "wait_for_refresh"
    assert payload["rag"]["refresh_job"]["status"] == "running"


def test_get_rag_runtime_status_handles_chroma_error(app, monkeypatch):
    class FailingChromaClient:
        def heartbeat(self):
            return 1

        def list_collections(self):
            raise RuntimeError("chroma unavailable")

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["normativa"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(logic, "_get_chroma_http_client", lambda: FailingChromaClient())

    with app.app_context():
        payload, status_code = logic.get_rag_runtime_status()

    assert status_code == 503
    assert payload == {
        "status": "not_ready",
        "service": "policy-agent",
        "rag": {
            "status": "error",
            "reason": "rag_status_unavailable",
        },
    }


def test_refresh_rag_runtime_rejects_when_disabled(app, monkeypatch):
    monkeypatch.delenv("POLICY_AGENT_ALLOW_RAG_REFRESH", raising=False)
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", None)

    with app.app_context():
        payload, status_code = logic.refresh_rag_runtime()

    assert status_code == 403
    assert payload["error_code"] == "rag_refresh_disabled"


def test_refresh_rag_runtime_returns_existing_running_job(app, monkeypatch):
    running_job = {
        "id": "job-running",
        "status": "running",
        "started_at": "2026-05-08T00:00:00+00:00",
    }

    class FailingThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("refresh_rag_runtime must not start another thread")

    monkeypatch.setenv("POLICY_AGENT_ALLOW_RAG_REFRESH", "1")
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", running_job)
    monkeypatch.setattr(logic.threading, "Thread", FailingThread)

    with app.app_context():
        payload, status_code = logic.refresh_rag_runtime()

    assert status_code == 202
    assert payload["success"] is True
    assert payload["message"] == "RAG refresh is already running."
    assert payload["job"] == running_job


def test_run_rag_refresh_command_uses_fixed_index_command(app, monkeypatch):
    captured = {}

    class Completed:
        returncode = 0
        stdout = "indexed"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setenv("POLICY_AGENT_ALLOW_RAG_REFRESH", "1")
    monkeypatch.setattr(logic.subprocess, "run", fake_run)
    monkeypatch.setattr(
        logic,
        "get_rag_runtime_status",
        lambda: ({"status": "ready", "rag": {"status": "ready"}}, 200),
    )

    with app.app_context():
        payload = logic._run_rag_refresh_command()

    assert payload["success"] is True
    assert captured["command"][-2:] == ["scripts/index_pdfs_to_chroma.py", "--reindex"]
    assert captured["kwargs"]["check"] is False


def test_run_rag_refresh_command_reports_failed_process(app, monkeypatch):
    class Completed:
        returncode = 2
        stdout = "indexed before failure"
        stderr = "chroma write failed"

    monkeypatch.setenv("POLICY_AGENT_ALLOW_RAG_REFRESH", "1")
    monkeypatch.setattr(logic.subprocess, "run", lambda *args, **kwargs: Completed())

    with app.app_context():
        payload = logic._run_rag_refresh_command()

    assert payload["success"] is False
    assert payload["error_code"] == "rag_refresh_failed"
    assert payload["details"] == {
        "return_code": 2,
        "stdout_chars": len("indexed before failure"),
        "stderr_chars": len("chroma write failed"),
        "output_suppressed": True,
    }


def test_refresh_rag_runtime_starts_background_job(app, monkeypatch):
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            captured["target"] = target
            captured["args"] = args
            captured["daemon"] = daemon

        def start(self):
            captured["started"] = True

    monkeypatch.setenv("POLICY_AGENT_ALLOW_RAG_REFRESH", "1")
    monkeypatch.setattr(logic.threading, "Thread", FakeThread)
    monkeypatch.setattr(logic, "_RAG_REFRESH_JOB", None)

    with app.app_context():
        payload, status_code = logic.refresh_rag_runtime()

    assert status_code == 202
    assert payload["success"] is True
    assert payload["job"]["status"] == "running"
    assert captured["daemon"] is True
    assert captured["started"] is True


def test_run_rag_refresh_job_updates_job_result_on_success(app, monkeypatch):
    monkeypatch.setattr(
        logic,
        "_RAG_REFRESH_JOB",
        {
            "id": "job-1",
            "status": "running",
            "started_at": "2026-05-08T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        logic,
        "_run_rag_refresh_command",
        lambda: {"success": True, "stage": "rag_refresh"},
    )

    logic._run_rag_refresh_job("job-1", app, "corr-1")

    job = logic.get_rag_refresh_job_status()
    assert job["status"] == "completed"
    assert job["completed_at"]
    assert job["result"] == {"success": True, "stage": "rag_refresh"}


def test_run_rag_refresh_job_updates_job_result_on_failure(app, monkeypatch):
    monkeypatch.setattr(
        logic,
        "_RAG_REFRESH_JOB",
        {
            "id": "job-1",
            "status": "running",
            "started_at": "2026-05-08T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        logic,
        "_run_rag_refresh_command",
        lambda: {"success": False, "error_code": "rag_refresh_failed"},
    )

    logic._run_rag_refresh_job("job-1", app, "corr-1")

    job = logic.get_rag_refresh_job_status()
    assert job["status"] == "failed"
    assert job["completed_at"]
    assert job["result"] == {"success": False, "error_code": "rag_refresh_failed"}


def test_run_rag_refresh_job_marks_unhandled_exception_failed(app, monkeypatch):
    monkeypatch.setattr(
        logic,
        "_RAG_REFRESH_JOB",
        {
            "id": "job-1",
            "status": "running",
            "started_at": "2026-05-08T00:00:00+00:00",
        },
    )

    def fail_refresh():
        raise RuntimeError("boom")

    monkeypatch.setattr(logic, "_run_rag_refresh_command", fail_refresh)

    logic._run_rag_refresh_job("job-1", app, "corr-1")

    job = logic.get_rag_refresh_job_status()
    assert job["status"] == "failed"
    assert job["completed_at"]
    assert job["result"]["success"] is False
    assert job["result"]["error_code"] == "rag_refresh_unhandled_exception"


def test_run_generation_pipeline_rejects_invalid_json_body(app_context):
    result = logic.run_generation_pipeline(None)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "invalid_json_body",
        "message": "Request body must be a JSON object.",
        "details": {"stage": "contract_validation", "expected_type": "object"},
        "status_code": 400,
    }


def test_run_generation_pipeline_rejects_oversized_prompt(app_context):
    payload = {
        "context_id": "ctx-oversized",
        "refined_prompt": "x" * (logic.MAX_PROMPT_LENGTH + 1),
        "language": "en",
        "model_version": "openai",
    }

    result = logic.run_generation_pipeline(payload)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "field_too_large",
        "message": "Field 'refined_prompt' exceeds the allowed size.",
        "details": {
            "stage": "contract_validation",
            "field": "refined_prompt",
            "max_length": logic.MAX_PROMPT_LENGTH,
        },
        "correlation_id": "ctx-oversized",
        "status_code": 413,
    }


def test_validate_generation_payload_accepts_optional_business_context(app_context):
    result = logic.validate_generation_payload(
        {
            "context_id": "ctx-business",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
            "business_context": {
                "country": "Spain",
                "sector": "Private healthcare",
                "important_assets": ["Medical records", "Backups"],
            },
        }
    )

    assert result["business_context"] == {
        "country": "Spain",
        "sector": "Private healthcare",
        "important_assets": ["Medical records", "Backups"],
    }


def test_validate_generation_payload_rejects_invalid_business_context(app_context):
    result = logic.run_generation_pipeline(
        {
            "context_id": "ctx-business",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
            "business_context": "country=Spain",
        }
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_field_type"
    assert result["details"]["field"] == "business_context"


def test_validate_generation_payload_rejects_nested_business_context_list(app_context):
    result = logic.run_generation_pipeline(
        {
            "context_id": "ctx-business",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
            "business_context": {
                "important_assets": ["Medical records", {"name": "Backups"}],
            },
        }
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_field_type"
    assert result["details"]["field"] == "business_context"
    assert result["details"]["key"] == "important_assets"


def test_run_generation_pipeline_persists_policy(app_context, monkeypatch):
    monkeypatch.setattr(
        logic,
        "run_with_agent",
        lambda **kwargs: {
            "text": "Generated policy body",
            "structured_plan": ["scope"],
            "retrieval_evidence": [
                {
                    "citation": "legal_norms:rgpd",
                    "collection": "legal_norms",
                    "source_id": "legal_norms",
                }
            ],
        },
    )

    result = logic.run_generation_pipeline(
        {
            "context_id": "ctx-1",
            "refined_prompt": "Generate policy",
            "language": "en",
            "model_version": "openai",
        }
    )

    assert result["success"] is True
    assert result["stage"] == "completed"
    assert result["policy"]["policy_text"] == "Generated policy body"
    stored_policy = mongo.db.policies.find_one({"context_id": "ctx-1"})
    assert stored_policy is not None
    assert stored_policy["ownership"]["owner_service"] == "policy-agent"
    assert stored_policy["correlation_id"] == "ctx-1"
    assert stored_policy["retrieval_evidence"] == [
        {
            "citation": "legal_norms:rgpd",
            "collection": "legal_norms",
            "source_id": "legal_norms",
        }
    ]


def test_run_generation_pipeline_emits_structured_logs(app_context, monkeypatch, caplog):
    monkeypatch.setattr(
        logic,
        "run_with_agent",
        lambda **kwargs: {"text": "Generated policy body", "structured_plan": ["scope"]},
    )

    with caplog.at_level("INFO"):
        result = logic.run_generation_pipeline(
            {
                "context_id": "ctx-log",
                "refined_prompt": "Generate policy",
                "language": "en",
                "model_version": "openai",
            }
        )

    assert result["success"] is True
    assert '"event": "policy.pipeline.generation_completed"' in caplog.text
    assert '"context_id": "ctx-log"' in caplog.text


def test_run_policy_update_pipeline_rejects_oversized_feedback_list(app_context):
    context_id = "ctx-update"
    mongo.db.policies.insert_one(
        {
            "_id": "policy-1",
            "context_id": context_id,
            "language": "en",
            "policy_text": "previous policy",
            "structured_plan": [],
            "model_version": "gpt-4",
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc),
        }
    )
    payload = {
        "context_id": context_id,
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": [f"reason-{idx}" for idx in range(logic.MAX_FEEDBACK_ITEMS + 1)],
        "recommendations": ["recommendation"],
    }

    result = logic.run_policy_update_pipeline(payload, context_id)

    assert result == {
        "success": False,
        "error_type": "contract_error",
        "error_code": "field_too_large",
        "message": "Field 'reasons' exceeds the allowed item count.",
        "details": {
            "stage": "contract_validation",
            "field": "reasons",
            "max_items": logic.MAX_FEEDBACK_ITEMS,
        },
        "correlation_id": context_id,
        "status_code": 413,
    }


def test_run_policy_update_pipeline_updates_existing_policy(app_context, monkeypatch):
    context_id = "ctx-existing"
    mongo.db.policies.insert_one(
        {
            "_id": "policy-2",
            "context_id": context_id,
            "language": "en",
            "policy_text": "previous policy",
            "structured_plan": ["old"],
            "retrieval_evidence": [{"citation": "legal_norms:rgpd"}],
            "model_version": "gpt-4",
            "policy_agent_version": "0.1.0",
            "generated_at": datetime.now(timezone.utc),
            "revision_count": 1,
        }
    )
    monkeypatch.setattr(
        logic,
        "update_with_agent",
        lambda **kwargs: {"text": "Updated policy body"},
    )
    payload = {
        "context_id": context_id,
        "language": "en",
        "policy_text": "policy text",
        "policy_agent_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review",
        "reasons": ["reason"],
        "recommendations": ["recommendation"],
    }

    result = logic.run_policy_update_pipeline(payload, context_id)

    assert result["success"] is True
    assert result["policy"]["policy_text"] == "Updated policy body"
    assert result["policy"]["revision_count"] == 2
    stored_policy = mongo.db.policies.find_one({"context_id": context_id})
    assert stored_policy["policy_text"] == "Updated policy body"
    assert stored_policy["last_validation_status"] == "review"
    assert stored_policy["correlation_id"] == context_id
    assert stored_policy["retrieval_evidence"] == [{"citation": "legal_norms:rgpd"}]


def test_build_policy_update_prompt_is_deterministic():
    prompt = logic.build_policy_update_prompt(
        "Original policy",
        ["Missing controls"],
        ["Add MFA"],
    )

    assert "[Original Policy]:" in prompt
    assert "- Missing controls" in prompt
    assert "- Add MFA" in prompt


def test_validate_generation_payload_prefers_request_correlation_id(app):
    payload = {
        "context_id": "ctx-from-payload",
        "refined_prompt": "Generate policy",
        "language": "en",
        "model_version": "openai",
    }

    with app.test_request_context(headers={"X-Correlation-ID": "ctx-from-header"}):
        g.correlation_id = "ctx-from-header"
        result = logic.validate_generation_payload(payload)

    assert result["correlation_id"] == "ctx-from-header"


def test_run_with_agent_propagates_request_correlation_id(app, monkeypatch):
    class FakeConfiguredClient:
        def __init__(self, headers):
            self.default_headers = headers
            self.chat = object()

    class FakeSdkClient:
        def __init__(self):
            self.calls = []

        def with_options(self, *, default_headers):
            self.calls.append(default_headers)
            return FakeConfiguredClient(default_headers)

    class FakeClientWrapper:
        def __init__(self, sdk_client):
            self.client = sdk_client
            self.chat = object()

    class FakeAgent:
        def __init__(self, sdk_client):
            self.client = FakeClientWrapper(sdk_client)
            self.roles = [{"PolicyGeneration": True}]

        def run(self, prompt, context_id=None, retrieval_plan=None):
            return {
                "text": "Generated policy body",
                "structured_plan": [],
                "used_headers": self.client.client.default_headers,
                "context_id": context_id,
                "retrieval_plan": retrieval_plan,
            }

    sdk_client = FakeSdkClient()
    fake_agent = FakeAgent(sdk_client)
    monkeypatch.setattr(logic, "load_policy_config", lambda: {"type": "mock", "name": "fake", "instructions": "", "model": "fake", "roles": [{"MPG": "unused", "instructions": "x"}]})
    monkeypatch.setattr(logic, "_store_policy_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(logic, "create_agent_from_config", lambda config: fake_agent)

    with app.test_request_context(headers={"X-Correlation-ID": "outbound-correlation-id"}):
        g.correlation_id = "outbound-correlation-id"
        result = logic.run_with_agent(
            refined_prompt="Generate policy",
            context_id="ctx-123",
            model_version="openai",
        )

    assert sdk_client.calls == [{"X-Correlation-ID": "outbound-correlation-id"}]
    assert result["used_headers"] == {"X-Correlation-ID": "outbound-correlation-id"}
