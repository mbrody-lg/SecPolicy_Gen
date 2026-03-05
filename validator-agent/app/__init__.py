"""Application bootstrap for validator-agent."""

import os
from flask import Flask
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Initialize global Mongo object
mongo = PyMongo()

def create_app():
    """Create and configure the Flask application for validator-agent."""
    # Load environment variables
    load_dotenv()

    # Create Flask app
    app = Flask(__name__)

    # Base configuration
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/validatordb")
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", "/validator-agent/app/config/validator_agent.yaml")
    app.config["TESTING"] = os.getenv("DEBUG", "false").lower() == "true"

    # Initialize Mongo with app
    mongo.init_app(app)

    # Import and register blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    return app
