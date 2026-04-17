"""Application bootstrap for validator-agent."""

import os
from flask import Flask
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Initialize global Mongo object
mongo = PyMongo()

TEST_ONLY_SECRET_KEY = "test-only-secret-key"


def _get_env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags using explicit truthy values only."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

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

    # Initialize Mongo with app
    mongo.init_app(app)

    # Import and register blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    return app
