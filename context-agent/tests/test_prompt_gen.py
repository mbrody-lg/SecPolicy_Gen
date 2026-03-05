from test_base import *

from app.services.logic import generate_context_prompt, load_questions

def test_question_loader():
    questions = load_questions()
    assert isinstance(questions, list)
    assert "question" in questions[0]

def test_prompt_generation():
    data = {
        "country": "Spain",
        "sector": "Healthcare",
        "important_assets": "Medical records",
        "critical_assets": "Clinical server",
        "current_security_operations": "Daily backups",
        "methodology": "Partial ISO 27001",
        "generic": "generic",
        "need": "adapt policies to ISO 27001:2022"
    }
    prompt = generate_context_prompt(data)
    assert "Spain" in prompt
    assert "Clinical server" in prompt
    assert "ISO 27001:2022" in prompt
