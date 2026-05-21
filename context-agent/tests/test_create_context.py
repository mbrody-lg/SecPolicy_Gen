from test_base import *
from app import create_app, mongo
import pytest
import app.routes.routes as routes_module

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_create_context(client, monkeypatch):
    monkeypatch.setattr(
        routes_module,
        "run_context_planning_review",
        lambda prompt, context_id, model_version=None: {
            "text": "Refined context from test",
            "structured_review": {
                "plan_summary": "Refined context from test",
                "tasks": [],
                "missing_context_questions": [],
                "approval_recommendation": "review_required",
            },
        },
    )

    # Test data
    country = "SpainCreateContextTest"
    form_data = {
        "country": country,
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

    context = mongo.db.contexts.find_one({"country": country})
    assert context is not None, "Context not found"
    assert context["status"] == "awaiting_task_validation"
    assert context["country"] == country
    assert context["security_context"]["profile"]["sector"] == "Healthcare"
    assert context["context_intelligence_plan"]["status"] == "draft"

    # Verify interactions were saved
    interactions = list(mongo.db.interactions.find({"context_id": context["_id"]}))
    assert len(interactions) >= 1, "No interactions saved."
    assert any(
        item.get("answer") == "Refined context from test"
        for item in interactions
    )

    print("Interactions count:", len(interactions))
