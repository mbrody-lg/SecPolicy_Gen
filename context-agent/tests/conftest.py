import pytest
from pathlib import Path
from types import SimpleNamespace

import mongomock

from test_base import *
import app as app_module
from app import create_app
from app.routes import routes as routes_module
from app.services import logic as logic_module

SERVICE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def service_cwd(monkeypatch):
    monkeypatch.chdir(SERVICE_ROOT)


@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    client = mongomock.MongoClient()
    fake_mongo = SimpleNamespace(cx=client, db=client.db, init_app=lambda app: None)
    monkeypatch.setattr(app_module, "mongo", fake_mongo)
    monkeypatch.setattr(routes_module, "mongo", fake_mongo)
    monkeypatch.setattr(logic_module, "mongo", fake_mongo)
    yield

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
