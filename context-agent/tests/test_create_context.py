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
    # Dades de prova
    form_data = {
        "country": "Espanya",
        "sector": "Salut",
        "important_assets": "Historials mèdics",
        "critical_assets": "Dades de pacients",
        "current_security_operations": "Tallafocs i còpies",
        "methodology": "ISO 27001",
        "generic": "generiques",
        "need": "Protecció de dades personals"
    }

    response = client.post("/create", data=form_data, follow_redirects=True)
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Context" in html or "context" in html

    # Esperem a que Mongo actualitzi el document
    context = None
    for _ in range(20):
        context = mongo.db.contexts.find_one({"country": "Espanya"}, sort=[("created_at", -1)])
        if context and context.get("status") == "completed":
            break
        time.sleep(0.5)

    assert context is not None, "Context not found"
    assert context["status"] == "completed"
    assert context["country"] == "Espanya"
    assert "refined_prompt" in context

    # Verifiquem que s’han desat interaccions
    interactions = list(mongo.db.interactions.find({"context_id": context["_id"]}))
    assert len(interactions) >= 1, "No interactions saved."

    print("Prompt:", context["refined_prompt"][:80])
    print("Nº interaccions:", len(interactions))

