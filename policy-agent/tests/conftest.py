import os
import pytest
import sys
from unittest.mock import patch
from pathlib import Path
import mongomock
from workload_test_keys import KEY_IDS, configure_test_workload_env, signing_key

# Ensure project root path is accessible
ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("FLASK_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("CONFIG_PATH", str(ROOT_PATH / "app" / "config" / "policy_agent.yaml"))
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
configure_test_workload_env()

# Import app and routes
from app import create_app, mongo
from app.workload_token import mint_token


@pytest.fixture(autouse=True)
def service_cwd(monkeypatch):
    monkeypatch.chdir(ROOT_PATH)

# Test app/context
@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["CONFIG_PATH"] = str(ROOT_PATH / "app/config/policy_agent.yaml")
    return app

@pytest.fixture(scope="function")
def app_context(app):
    with app.app_context():
        yield

# HTTP test client
@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def workload_headers(app):
    def issue(path, *, subject=None, scope=None, audience="policy-agent", tenant_id="tenant-a"):
        if path == "/generate_policy":
            subject = subject or "context-agent"
            scope = scope or "policy:generate"
        elif path == "/rag/refresh":
            subject = subject or "context-agent"
            scope = scope or "policy:rag:refresh"
        elif path == "/candidate/generate-policy":
            subject = subject or "docker-agent"
            scope = scope or "policy:candidate:generate"
        else:
            subject = subject or "validator-agent"
            scope = scope or "policy:update"
        token = mint_token(
            key=signing_key(subject),
            kid=KEY_IDS[subject],
            subject=subject,
            audience=audience,
            scope=scope,
            tenant_id=tenant_id,
            path=path,
        )
        return {"Authorization": f"Bearer {token}"}

    return issue

# Default Mongo patch
@pytest.fixture(autouse=True)
def mock_mongo():
    with patch.object(mongo, "cx", mongomock.MongoClient()):
        with patch.object(mongo, "db", mongomock.MongoClient().db):
            yield

# Default test inputs
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
