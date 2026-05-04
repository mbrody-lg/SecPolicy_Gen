"""Application bootstrap for validator-agent."""

import os
import re
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask
from flask import g
from flask import has_request_context
from flask import request
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Initialize global Mongo object
mongo = PyMongo()

TEST_ONLY_SECRET_KEY = "test-only-secret-key"
CORRELATION_ID_HEADER = "X-Correlation-ID"
CORRELATION_ID_MAX_LENGTH = 128
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags using explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_float(name: str, default: float) -> float:
    """Parse positive float environment flags with a safe fallback."""
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
    """Parse positive integer environment flags with a safe fallback."""
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


def _resolve_request_correlation_id() -> str:
    """Preserve a safe inbound correlation id or create a request-scoped fallback."""
    inbound = getattr(g, "correlation_id", None)
    if (
        inbound
        and len(inbound) <= CORRELATION_ID_MAX_LENGTH
        and CORRELATION_ID_PATTERN.fullmatch(inbound)
    ):
        return inbound
    return uuid4().hex


def _normalize_correlation_id(value: str | None) -> str:
    """Return a safe correlation id, generating a fallback for unsafe input."""
    candidate = (value or "").strip()
    if (
        candidate
        and len(candidate) <= CORRELATION_ID_MAX_LENGTH
        and CORRELATION_ID_PATTERN.fullmatch(candidate)
    ):
        return candidate
    return uuid4().hex


def get_request_correlation_id() -> str | None:
    """Return the current request correlation id when a request context is active."""
    if not has_request_context():
        return None
    return getattr(g, "correlation_id", None)


def _response_correlation_id(response) -> str:
    """Return the request-scoped correlation id for response headers."""
    return _resolve_request_correlation_id()


def create_app():
    """Create and configure the Flask application for validator-agent."""
    # Load environment variables
    load_dotenv()

    # Create Flask app
    app = Flask(__name__)

    is_testing = _get_env_bool("TESTING", default=False)
    secret_key = _get_required_env(
        "FLASK_SECRET_KEY",
        is_testing=is_testing,
        test_default=TEST_ONLY_SECRET_KEY,
    )

    # Base configuration
    app.config["SECRET_KEY"] = secret_key
    app.config["MONGO_URI"] = _validate_mongo_uri(
        "MONGO_URI",
        _get_required_env(
            "MONGO_URI",
            is_testing=is_testing,
            test_default="mongodb://mongo:27017/validatordb",
        ),
    )
    app.config["CONFIG_PATH"] = _get_required_env(
        "CONFIG_PATH",
        is_testing=is_testing,
        test_default="/validator-agent/app/config/validator_agent.yaml",
    )
    app.config["TESTING"] = is_testing
    app.config["DEBUG"] = _get_env_bool("DEBUG", default=False)
    app.config["POLICY_AGENT_URL"] = _validate_http_url(
        "POLICY_AGENT_URL",
        _get_required_env(
            "POLICY_AGENT_URL",
            is_testing=is_testing,
            test_default="http://policy-agent:5000",
        ),
    )
    app.config["POLICY_AGENT_TIMEOUT_SECONDS"] = _get_env_float("POLICY_AGENT_TIMEOUT_SECONDS", 30.0)
    app.config["MAX_CONTENT_LENGTH"] = _get_env_int("MAX_CONTENT_LENGTH", 256 * 1024)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _get_env_bool("SESSION_COOKIE_SECURE", default=False)
    trusted_hosts = _get_env_list("TRUSTED_HOSTS")
    if trusted_hosts is not None:
        app.config["TRUSTED_HOSTS"] = trusted_hosts

    # Initialize Mongo with app
    mongo.init_app(app)

    # Import and register blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    @app.before_request
    def attach_correlation_id():
        inbound = g.get("correlation_id")
        if inbound:
            return

        g.correlation_id = _normalize_correlation_id(request.headers.get(CORRELATION_ID_HEADER))

    @app.after_request
    def apply_security_headers(response):
        correlation_id = _response_correlation_id(response)
        if response.is_json and correlation_id and request.path != "/ready":
            payload = response.get_json(silent=True)
            if isinstance(payload, dict) and payload.get("success") is False:
                payload["correlation_id"] = correlation_id
                response.set_data(app.json.dumps(payload))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(CORRELATION_ID_HEADER, correlation_id)
        return response

    return app
