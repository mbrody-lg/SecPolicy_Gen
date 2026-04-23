"""Application factory for the context-agent service."""

import os
from uuid import uuid4

from flask import Flask, g, has_request_context, request
from flask_pymongo import PyMongo
from dotenv import load_dotenv

mongo = PyMongo()

TEST_ONLY_SECRET_KEY = "test-only-secret-key"


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags using explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_float(name: str, default: float) -> float:
    """Parse float environment values with a safe fallback."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    """Parse integer environment values with a safe fallback."""
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


def get_request_correlation_id() -> str | None:
    """Return the request correlation id when available."""
    if not has_request_context():
        return None
    return getattr(g, "correlation_id", None)


def _ensure_correlation_id() -> str:
    """Preserve inbound correlation id or create one for the request lifecycle."""
    correlation_id = request.headers.get("X-Correlation-ID")
    if correlation_id:
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
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        if is_testing:
            secret_key = TEST_ONLY_SECRET_KEY
        else:
            raise ValueError("FLASK_SECRET_KEY must be set when TESTING is false.")

    app.config["SECRET_KEY"] = secret_key
    app.config["TESTING"] = is_testing
    app.config["DEBUG"] = _get_env_bool("DEBUG", default=False)
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/contextdb")
    app.config["POLICY_AGENT_URL"] = os.getenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    app.config["VALIDATOR_AGENT_URL"] = os.getenv("VALIDATOR_AGENT_URL", "http://validator-agent:5000")
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
        config = load_agent_config("app/config/context_agent.yaml")
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
            response.headers["X-Correlation-ID"] = correlation_id
            if _is_json_response(response):
                payload = response.get_json(silent=True)
                if isinstance(payload, dict) and "correlation_id" in payload:
                    payload["correlation_id"] = correlation_id
                    response.set_data(
                        app.json.dumps(payload) + ("\n" if response.get_data(as_text=True).endswith("\n") else "")
                    )

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app
