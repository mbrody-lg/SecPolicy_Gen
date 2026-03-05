"""Application factory and extensions for the policy-agent service."""

import os
from flask import Flask
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Initialize global Mongo object
mongo = PyMongo()

def create_app():
    """Build and configure the Flask app and register routes."""
    # Load environment variables from .env
    load_dotenv()

    # Create Flask app
    app = Flask(__name__)

    # Security and database settings
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "1FQj9YHGCbxRkWswvw$ds")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/policydb")
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", "/config/policy_agent.yaml")
    app.config["DEBUG"] = True


    # Initialize Mongo with app
    mongo.init_app(app)
    
    # Import and register blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    return app
