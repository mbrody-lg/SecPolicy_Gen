"""Application factory for the context-agent service."""

import os

from flask import Flask
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
    mongo.init_app(app)


    @app.context_processor
    def inject_agent_type():
        from app.agents.factory import load_agent_config
        config = load_agent_config("app/config/context_agent.yaml")
        return {"agent_type": config.get("type", "unknown")}

    from app.routes.routes import main
    app.register_blueprint(main)

    return app
