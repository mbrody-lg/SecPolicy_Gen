from flask import Flask
from flask_pymongo import PyMongo
import os
from dotenv import load_dotenv

mongo = PyMongo()

def create_app():
    load_dotenv()
    
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "GzzR64t#FfR66Y#wCt$R")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://mongo:27017/contextdb")
    app.config["POLICY_AGENT_URL"] = os.getenv("POLICY_AGENT_URL", "http://policy-agent:5000")
    app.config["VALIDATOR_AGENT_URL"] = os.getenv("VALIDATOR_AGENT_URL", "http://validator-agent:5000")
    mongo.init_app(app)


    @app.context_processor
    def inject_agent_type():
        from app.agents.factory import load_agent_config
        config = load_agent_config("app/config/context_agent.yaml")
        return dict(agent_type=config.get("type", "unknown"))

    from app.routes.routes import main
    app.register_blueprint(main)

    return app