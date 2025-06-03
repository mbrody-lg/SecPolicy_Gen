import os
from flask import Flask
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Inicialitza l'objecte Mongo globalment
mongo = PyMongo()

def create_app():
    # Carrega les variables d'entorn
    load_dotenv()

    # Crea l'app Flask
    app = Flask(__name__)

    # Configuració bàsica
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/validatordb")
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", "/validator-agent/app/config/validator_agent.yaml")
    app.config["TESTING"] = os.getenv("DEBUG", "false").lower() == "true"

    # Inicialitza Mongo amb l'app
    mongo.init_app(app)

    # Importa i registra els blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    return app
