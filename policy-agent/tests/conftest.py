import pytest
import sys
from unittest.mock import patch
from pathlib import Path
from flask import Flask
import mongomock

# Assegurem que el path arrel del projecte és accessible
ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

# Importem l'app original i les rutes correctes
from app import create_app, mongo

# App i context de test
@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture(scope="function")
def app_context(app):
    with app.app_context():
        yield

# Client per a tests HTTP
@pytest.fixture()
def client(app):
    return app.test_client()

# Mongo patch per defecte
@pytest.fixture(autouse=True)
def mock_mongo():
    with patch.object(mongo, "cx", mongomock.MongoClient()):
        with patch.object(mongo, "db", mongomock.MongoClient().db):
            yield

# Inputs per defecte de tests
@pytest.fixture(scope="session")
def default_prompt():
    return "Generate a security policy for a spanish SME with GDPR and ISO 27001 requirements."

@pytest.fixture(scope="session")
def default_language():
    return "en"

@pytest.fixture(scope="session")
def default_context_id():
    return "6825a0e00194d322881db128"

@pytest.fixture(scope="session")
def mock_model_version():
    return "mock"

@pytest.fixture(scope="session")
def openai_model_version():
    return "openai"
