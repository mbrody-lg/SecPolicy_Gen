from pathlib import Path

import pytest

import app as app_module


def _set_common_env(monkeypatch):
    monkeypatch.setattr(app_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("MONGO_URI", "mongodb://mongo:27017/validatordb")
    monkeypatch.setenv(
        "CONFIG_PATH",
        str(Path(__file__).resolve().parents[1] / "app" / "config" / "validator_agent.yaml"),
    )


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
