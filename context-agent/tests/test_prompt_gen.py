from test_base import *

from app.services.logic import generate_context_prompt, load_questions

def test_question_loader():
    questions = load_questions()
    assert isinstance(questions, list)
    assert "question" in questions[0]

def test_prompt_generation():
    data = {
        "country": "Espanya",
        "sector": "Salut",
        "important_assets": "Historials mèdics",
        "critical_assets": "Servidor clínic",
        "current_security_operations": "Backup diari",
        "methodology": "ISO 27001 parcial",
        "generic": "generiques",
        "need": "adaptar les politiques a ISO 27001:2022"
    }
    prompt = generate_context_prompt(data)
    assert "Espanya" in prompt
    assert "Servidor clínic" in prompt
    assert "ISO 27001:2022" in prompt
