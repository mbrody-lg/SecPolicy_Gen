"""Application factory and extensions for the policy-agent service."""

import os
from flask import Flask
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Initialize global Mongo object
mongo = PyMongo()

TEST_ONLY_SECRET_KEY = "test-only-secret-key"


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags with explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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

    # Initialize Mongo with app
    mongo.init_app(app)
    
    # Import and register blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    return app
