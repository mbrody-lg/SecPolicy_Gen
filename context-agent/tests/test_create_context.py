from test_base import *
from app import create_app, mongo
import pytest
import time

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_create_context(client):
    # Test data
    form_data = {
        "country": "Spain",
        "sector": "Healthcare",
        "important_assets": "Medical records",
        "critical_assets": "Patient data",
        "current_security_operations": "Firewalls and backups",
        "methodology": "ISO 27001",
        "generic": "generic",
        "need": "Personal data protection"
    }

    response = client.post("/create", data=form_data, follow_redirects=True)
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Context" in html or "context" in html

    # Wait for Mongo to update document
    context = None
    for _ in range(20):
        context = mongo.db.contexts.find_one({"country": "Spain"}, sort=[("created_at", -1)])
        if context and context.get("status") == "completed":
            break
        time.sleep(0.5)

    assert context is not None, "Context not found"
    assert context["status"] == "completed"
    assert context["country"] == "Spain"
    assert "refined_prompt" in context

    # Verify interactions were saved
    interactions = list(mongo.db.interactions.find({"context_id": context["_id"]}))
    assert len(interactions) >= 1, "No interactions saved."

    print("Prompt:", context["refined_prompt"][:80])
    print("Interactions count:", len(interactions))
