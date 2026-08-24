import os
import sys
from pathlib import Path
from unittest.mock import patch

import mongomock
import pytest

from test_base import *
from app import create_app
from app import mongo

ROOT_PATH = Path(__file__).resolve().parents[1]

if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("FLASK_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("MONGO_URI", "mongodb://mongo:27017/context-testdb")

TEST_PRINCIPAL = {
    "issuer": "https://identity.test/tenant/secpolicygen",
    "subject": "test-operator",
    "email": "operator@example.test",
    "name": "Test Operator",
}
TEST_ORGANIZATION_ID = "test-organization"


def _stamp_tenant_test_inserts(db):
    """Keep legacy route fixtures explicit to the authenticated test tenant."""
    for collection_name in ("contexts", "interactions", "pipeline_jobs", "pipeline_events", "pipeline_diagnostics"):
        collection = getattr(db, collection_name)
        original_insert_one = collection.insert_one

        def insert_one(document, *args, _insert=original_insert_one, **kwargs):
            document.setdefault("organization_id", TEST_ORGANIZATION_ID)
            return _insert(document, *args, **kwargs)

        collection.insert_one = insert_one
        original_insert_many = collection.insert_many

        def insert_many(documents, *args, _insert=original_insert_many, **kwargs):
            for document in documents:
                document.setdefault("organization_id", TEST_ORGANIZATION_ID)
            return _insert(documents, *args, **kwargs)

        collection.insert_many = insert_many


def authenticate_test_client(test_client):
    """Establish the minimal signed session produced by the OIDC callback."""
    from app.access_control import provision_membership, provision_organization, sync_principal

    with test_client.application.app_context():
        principal = sync_principal(
            issuer=TEST_PRINCIPAL["issuer"],
            subject=TEST_PRINCIPAL["subject"],
        )
        organization = provision_organization(
            organization_id="test-organization",
            name="Test Organization",
        )
        provision_membership(
            principal_id=principal["_id"],
            organization_id=organization["organization_id"],
            roles=["admin"],
            is_default=True,
        )
    with test_client.session_transaction() as session:
        session["principal"] = TEST_PRINCIPAL
    return test_client


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    monkeypatch.chdir(ROOT_PATH)
    with patch.object(mongo, "cx", mongomock.MongoClient()):
        with patch.object(mongo, "db", mongomock.MongoClient().db):
            yield


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    mock_client = mongomock.MongoClient()
    with patch.object(mongo, "cx", mock_client):
        with patch.object(mongo, "db", mock_client.db):
            _stamp_tenant_test_inserts(mock_client.db)
            yield authenticate_test_client(app.test_client())


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    mock_client = mongomock.MongoClient()
    with patch.object(mongo, "cx", mock_client):
        with patch.object(mongo, "db", mock_client.db):
            _stamp_tenant_test_inserts(mock_client.db)
            yield flask_app


@pytest.fixture
def app_context(app):
    with app.app_context():
        yield
