"""Application factory for the context-agent service."""

import os
import re
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask, g, has_request_context, request
from flask_pymongo import PyMongo
from dotenv import load_dotenv

mongo = PyMongo()

TEST_ONLY_SECRET_KEY = "test-only-secret-key"
CORRELATION_ID_HEADER = "X-Correlation-ID"
CORRELATION_ID_MAX_LENGTH = 128
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
DEFAULT_CONFIG_PATH = "app/config/context_agent.yaml"
DEFAULT_QUESTIONS_CONFIG_PATH = "app/config/context_questions.yaml"


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags using explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_float(name: str, default: float) -> float:
    """Parse positive float environment values with a safe fallback."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        raise ValueError(f"{name} must be a positive number.") from None
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return parsed


def _get_env_int(name: str, default: int) -> int:
    """Parse positive integer environment values with a safe fallback."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(f"{name} must be a positive integer.") from None
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def _get_env_list(name: str) -> list[str] | None:
    """Parse comma-separated environment values."""
    value = os.getenv(name)
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError(f"{name} must include at least one value when set.")
    return items


def _get_required_env(name: str, *, is_testing: bool, test_default: str | None = None) -> str:
    """Read a required environment value, allowing explicit test-only defaults."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    if is_testing and test_default is not None:
        return test_default
    raise ValueError(f"{name} must be set when TESTING is false.")


def _validate_http_url(name: str, value: str) -> str:
    """Validate a configured HTTP service URL without exposing the raw value."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http(s) URL.")
    return value


def _validate_mongo_uri(name: str, value: str) -> str:
    """Validate a MongoDB URI without exposing the raw value."""
    parsed = urlparse(value)
    if parsed.scheme not in {"mongodb", "mongodb+srv"} or not parsed.netloc:
        raise ValueError(f"{name} must be a MongoDB URI.")
    return value


def get_request_correlation_id() -> str | None:
    """Return the request correlation id when available."""
    if not has_request_context():
        return None
    return getattr(g, "correlation_id", None)


def _ensure_correlation_id() -> str:
    """Preserve a safe inbound correlation id or create one for the request lifecycle."""
    correlation_id = request.headers.get(CORRELATION_ID_HEADER, "").strip()
    if (
        correlation_id
        and len(correlation_id) <= CORRELATION_ID_MAX_LENGTH
        and CORRELATION_ID_PATTERN.fullmatch(correlation_id)
    ):
        return correlation_id
    return str(uuid4())


def _is_json_response(response) -> bool:
    """Check whether the response carries a JSON payload."""
    content_type = (response.content_type or "").split(";", 1)[0].strip().lower()
    return response.is_json or content_type == "application/json"

def create_app():
    """Create and configure the Flask application instance."""
    load_dotenv()

    app = Flask(__name__)
    is_testing = _get_env_bool("TESTING", default=False)
    secret_key = _get_required_env(
        "FLASK_SECRET_KEY",
        is_testing=is_testing,
        test_default=TEST_ONLY_SECRET_KEY,
    )

    app.config["SECRET_KEY"] = secret_key
    app.config["TESTING"] = is_testing
    app.config["DEBUG"] = _get_env_bool("DEBUG", default=False)
    app.config["MONGO_URI"] = _validate_mongo_uri(
        "MONGO_URI",
        _get_required_env(
            "MONGO_URI",
            is_testing=is_testing,
            test_default="mongodb://mongo:27017/contextdb",
        ),
    )
    app.config["POLICY_AGENT_URL"] = _validate_http_url(
        "POLICY_AGENT_URL",
        _get_required_env(
            "POLICY_AGENT_URL",
            is_testing=is_testing,
            test_default="http://policy-agent:5000",
        ),
    )
    app.config["VALIDATOR_AGENT_URL"] = _validate_http_url(
        "VALIDATOR_AGENT_URL",
        _get_required_env(
            "VALIDATOR_AGENT_URL",
            is_testing=is_testing,
            test_default="http://validator-agent:5000",
        ),
    )
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", DEFAULT_CONFIG_PATH)
    app.config["QUESTIONS_CONFIG_PATH"] = os.getenv("QUESTIONS_CONFIG_PATH", DEFAULT_QUESTIONS_CONFIG_PATH)
    app.config["POLICY_AGENT_TIMEOUT_SECONDS"] = _get_env_float("POLICY_AGENT_TIMEOUT_SECONDS", 30.0)
    app.config["VALIDATOR_AGENT_TIMEOUT_SECONDS"] = _get_env_float("VALIDATOR_AGENT_TIMEOUT_SECONDS", 30.0)
    app.config["MAX_CONTENT_LENGTH"] = _get_env_int("MAX_CONTENT_LENGTH", 256 * 1024)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _get_env_bool("SESSION_COOKIE_SECURE", default=False)
    trusted_hosts = _get_env_list("TRUSTED_HOSTS")
    if trusted_hosts is not None:
        app.config["TRUSTED_HOSTS"] = trusted_hosts
    mongo.init_app(app)


    @app.context_processor
    def inject_agent_type():
        from app.agents.factory import load_agent_config
        config = load_agent_config(app.config["CONFIG_PATH"])
        return {"agent_type": config.get("type", "unknown")}

    from app.routes.routes import main
    app.register_blueprint(main)

    @app.before_request
    def bind_correlation_id():
        g.correlation_id = _ensure_correlation_id()

    @app.after_request
    def apply_security_headers(response):
        correlation_id = get_request_correlation_id()
        if correlation_id:
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            if _is_json_response(response):
                payload = response.get_json(silent=True)
                if isinstance(payload, dict) and payload.get("success") is False and "correlation_id" in payload:
                    payload["correlation_id"] = correlation_id
                    response.set_data(
                        app.json.dumps(payload) + ("\n" if response.get_data(as_text=True).endswith("\n") else "")
                    )

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app
