from unittest.mock import patch
from uuid import UUID

import pytest

import app as app_module


def _set_common_env(monkeypatch):
    monkeypatch.setattr(app_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("MONGO_URI", "mongodb://mongo:27017/contextdb")
    monkeypatch.setenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    monkeypatch.setenv("VALIDATOR_AGENT_URL", "http://validator-agent:5000")


def test_create_app_requires_secret_key_outside_testing(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    with pytest.raises(ValueError, match="FLASK_SECRET_KEY must be set"):
        app_module.create_app()


@pytest.mark.parametrize(
    "missing_variable",
    [
        "MONGO_URI",
        "POLICY_AGENT_URL",
        "VALIDATOR_AGENT_URL",
    ],
)
def test_create_app_requires_runtime_config_outside_testing(monkeypatch, missing_variable):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-secret")
    monkeypatch.delenv(missing_variable, raising=False)

    with pytest.raises(ValueError, match=f"{missing_variable} must be set"):
        app_module.create_app()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("MONGO_URI", "not-a-mongo-uri", "MONGO_URI must be a MongoDB URI"),
        ("POLICY_AGENT_URL", "policy-agent:5000", "POLICY_AGENT_URL must be an http"),
        ("VALIDATOR_AGENT_URL", "validator-agent:5000", "VALIDATOR_AGENT_URL must be an http"),
        ("POLICY_AGENT_TIMEOUT_SECONDS", "0", "POLICY_AGENT_TIMEOUT_SECONDS must be a positive number"),
        ("POLICY_AGENT_TIMEOUT_SECONDS", "not-a-number", "POLICY_AGENT_TIMEOUT_SECONDS must be a positive number"),
        ("VALIDATOR_AGENT_TIMEOUT_SECONDS", "-1", "VALIDATOR_AGENT_TIMEOUT_SECONDS must be a positive number"),
        ("MAX_CONTENT_LENGTH", "0", "MAX_CONTENT_LENGTH must be a positive integer"),
        ("MAX_CONTENT_LENGTH", "not-an-int", "MAX_CONTENT_LENGTH must be a positive integer"),
        ("TRUSTED_HOSTS", " , , ", "TRUSTED_HOSTS must include at least one value"),
    ],
)
def test_create_app_rejects_malformed_runtime_config(monkeypatch, variable, value, message):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        app_module.create_app()


def test_create_app_allows_placeholder_secret_in_testing(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    app = app_module.create_app()

    assert app.config["TESTING"] is True
    assert app.config["DEBUG"] is False
    assert app.config["SECRET_KEY"] == app_module.TEST_ONLY_SECRET_KEY


@pytest.mark.parametrize(
    ("debug_value", "expected"),
    [
        (None, False),
        ("false", False),
        ("1", True),
        ("true", True),
        ("yes", True),
    ],
)
def test_create_app_reads_debug_flag_from_env(monkeypatch, debug_value, expected):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")
    if debug_value is None:
        monkeypatch.delenv("DEBUG", raising=False)
    else:
        monkeypatch.setenv("DEBUG", debug_value)

    app = app_module.create_app()

    assert app.config["DEBUG"] is expected


def test_create_app_sets_dependency_timeouts_and_secure_defaults(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")
    monkeypatch.delenv("POLICY_AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("VALIDATOR_AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MAX_CONTENT_LENGTH", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("TRUSTED_HOSTS", raising=False)
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.delenv("QUESTIONS_CONFIG_PATH", raising=False)

    app = app_module.create_app()

    assert app.config["CONFIG_PATH"] == app_module.DEFAULT_CONFIG_PATH
    assert app.config["QUESTIONS_CONFIG_PATH"] == app_module.DEFAULT_QUESTIONS_CONFIG_PATH
    assert app.config["POLICY_AGENT_TIMEOUT_SECONDS"] == 30.0
    assert app.config["VALIDATOR_AGENT_TIMEOUT_SECONDS"] == 30.0
    assert app.config["MAX_CONTENT_LENGTH"] == 256 * 1024
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_create_app_reads_timeout_and_trusted_host_overrides(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")
    monkeypatch.setenv("POLICY_AGENT_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("VALIDATOR_AGENT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("MAX_CONTENT_LENGTH", "4096")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("TRUSTED_HOSTS", "localhost,context-agent.internal")
    monkeypatch.setenv("CONFIG_PATH", "/config/context_agent.yaml")
    monkeypatch.setenv("QUESTIONS_CONFIG_PATH", "/config/context_questions.yaml")

    app = app_module.create_app()

    assert app.config["CONFIG_PATH"] == "/config/context_agent.yaml"
    assert app.config["QUESTIONS_CONFIG_PATH"] == "/config/context_questions.yaml"
    assert app.config["POLICY_AGENT_TIMEOUT_SECONDS"] == 12.5
    assert app.config["VALIDATOR_AGENT_TIMEOUT_SECONDS"] == 45.0
    assert app.config["MAX_CONTENT_LENGTH"] == 4096
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["TRUSTED_HOSTS"] == ["localhost", "context-agent.internal"]


def test_request_hook_preserves_inbound_correlation_id(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")

    app = app_module.create_app()

    with app.test_request_context("/", headers={"X-Correlation-ID": "corr-inbound"}):
        app.preprocess_request()
        assert app_module.get_request_correlation_id() == "corr-inbound"


@pytest.mark.parametrize(
    "unsafe_correlation_id",
    [
        "corr inbound",
        "<script>alert(1)</script>",
        "x" * (app_module.CORRELATION_ID_MAX_LENGTH + 1),
    ],
)
def test_request_hook_regenerates_unsafe_inbound_correlation_id(monkeypatch, unsafe_correlation_id):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")

    app = app_module.create_app()

    with app.test_request_context("/", headers={"X-Correlation-ID": unsafe_correlation_id}):
        app.preprocess_request()
        generated = app_module.get_request_correlation_id()

    assert generated
    assert generated != unsafe_correlation_id
    UUID(generated)


def test_agent_type_context_processor_uses_config_path(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")
    monkeypatch.setenv("CONFIG_PATH", "/config/custom-context-agent.yaml")
    captured = {}

    def fake_load_agent_config(config_path):
        captured["config_path"] = config_path
        return {"type": "mock"}

    monkeypatch.setattr("app.agents.factory.load_agent_config", fake_load_agent_config)

    app = app_module.create_app()
    agent_type_context_processor = app.template_context_processors[None][-1]

    assert agent_type_context_processor() == {"agent_type": "mock"}
    assert captured["config_path"] == "/config/custom-context-agent.yaml"


def test_request_hook_generates_correlation_id_when_missing(monkeypatch):
    _set_common_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-test-secret")

    app = app_module.create_app()

    with app.test_request_context("/"):
        app.preprocess_request()
        generated = app_module.get_request_correlation_id()

    assert generated
    UUID(generated)
