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

    app = app_module.create_app()

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

    app = app_module.create_app()

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
