import os
from flask import Flask
from flask_pymongo import PyMongo
from dotenv import load_dotenv

# Inicialitza l'objecte global de Mongo
mongo = PyMongo()

def create_app():
    # Carrega variables d'entorn des de .env
    load_dotenv()

    # Crea l'app Flask
    app = Flask(__name__)

    # Configuració de seguretat i base de dades
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "1FQj9YHGCbxRkWswvw$ds")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/policydb")
    app.config["CONFIG_PATH"] = os.getenv("CONFIG_PATH", "/config/policy_agent.yaml")
    app.config["DEBUG"] = True


    # Inicialitza Mongo amb l'app
    mongo.init_app(app)
    
    # Importa i registra els blueprints
    from app.routes.routes import routes
    app.register_blueprint(routes)

    return app
