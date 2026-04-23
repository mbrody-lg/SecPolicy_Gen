"""Application bootstrap for validator-agent."""

import os
from uuid import uuid4

from flask import Flask
from flask import g
from flask import has_request_context
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Initialize global Mongo object
mongo = PyMongo()

TEST_ONLY_SECRET_KEY = "test-only-secret-key"
CORRELATION_ID_HEADER = "X-Correlation-ID"


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags using explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_float(name: str, default: float) -> float:
    """Parse float environment flags with a safe fallback."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    """Parse integer environment flags with a safe fallback."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_list(name: str) -> list[str] | None:
    """Parse comma-separated environment values."""
    value = os.getenv(name)
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _resolve_request_correlation_id() -> str:
    """Preserve inbound correlation ids or create a request-scoped fallback."""
    inbound = getattr(g, "correlation_id", None)
    if inbound:
        return inbound
    return uuid4().hex


def get_request_correlation_id() -> str | None:
    """Return the current request correlation id when a request context is active."""
    if not has_request_context():
        return None
    return getattr(g, "correlation_id", None)


def _response_correlation_id(response) -> str:
    """Prefer the response body correlation id when present, otherwise use request scope."""
    if response.is_json:
        payload = response.get_json(silent=True)
        if isinstance(payload, dict) and payload.get("correlation_id"):
            return str(payload["correlation_id"])
    return _resolve_request_correlation_id()

def create_app():
    """Create and configure the Flask application for validator-agent."""
    # Load environment variables
    load_dotenv()

    # Create Flask app
    app = Flask(__name__)

    is_testing = _get_env_bool("TESTING", default=False)
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        if is_testing:
            secret_key = TEST_ONLY_SECRET_KEY
        else:
            raise ValueError("FLASK_SECRET_KEY must be set when TESTING is false.")

    # Base configuration
    app.config["SECRET_KEY"] = secret_key
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/validatordb")
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", "/validator-agent/app/config/validator_agent.yaml")
    app.config["TESTING"] = is_testing
    app.config["DEBUG"] = _get_env_bool("DEBUG", default=False)
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
        from flask import request

        request_correlation_id = request.headers.get(CORRELATION_ID_HEADER)
        g.correlation_id = request_correlation_id or uuid4().hex

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(CORRELATION_ID_HEADER, _response_correlation_id(response))
        return response

    return app
