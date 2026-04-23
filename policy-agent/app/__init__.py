"""Application factory and extensions for the policy-agent service."""

import json
import os
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


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags with explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    """Parse comma-separated configuration values."""
    value = os.getenv(name)
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def get_request_correlation_id() -> str | None:
    """Return the request correlation id when a request context is active."""
    if not has_request_context():
        return None

    correlation_id = getattr(g, "correlation_id", None)
    if correlation_id:
        return correlation_id

    header_value = request.headers.get(CORRELATION_ID_HEADER, "").strip()
    return header_value or None


def create_app():
    """Build and configure the Flask app and register routes."""
    # Load environment variables from .env
    load_dotenv()

    # Create Flask app
    app = Flask(__name__)

    is_testing = _get_env_bool("TESTING", default=False)
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        if is_testing:
            # Tests may bootstrap with a non-production placeholder secret.
            secret_key = TEST_ONLY_SECRET_KEY
        else:
            raise ValueError("FLASK_SECRET_KEY must be set when TESTING is false.")

    # Security and database settings
    app.config["SECRET_KEY"] = secret_key
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/policydb")
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", "/config/policy_agent.yaml")
    app.config["TESTING"] = is_testing
    app.config["DEBUG"] = _get_env_bool("DEBUG", default=False)
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
    def assign_correlation_id():
        incoming_correlation_id = request.headers.get(CORRELATION_ID_HEADER, "").strip()
        g.correlation_id = incoming_correlation_id or str(uuid4())

    @app.after_request
    def apply_security_headers(response):
        correlation_id = get_request_correlation_id()
        if response.is_json and correlation_id:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict) and payload.get("success") is False:
                payload.setdefault("correlation_id", correlation_id)
                response.set_data(json.dumps(payload))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        if correlation_id:
            response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response

    return app
