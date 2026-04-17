import os
import sys
from pathlib import Path
from unittest.mock import patch

import mongomock
import pytest
from pathlib import Path
from types import SimpleNamespace

import mongomock

from test_base import *
import app as app_module
from app import create_app
from app import mongo

ROOT_PATH = Path(__file__).resolve().parents[1]

if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("FLASK_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("MONGO_URI", "mongodb://mongo:27017/context-testdb")


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    monkeypatch.chdir(ROOT_PATH)
    with patch.object(mongo, "cx", mongomock.MongoClient()):
        with patch.object(mongo, "db", mongomock.MongoClient().db):
            yield


@pytest.fixture
def client():
    with patch.object(mongo, "cx", mongomock.MongoClient()):
        with patch.object(mongo, "db", mongomock.MongoClient().db):
            app = create_app()
            app.config["TESTING"] = True
            yield app.test_client()
