from test_base import *

from app.services import logic
from app.services.logic import generate_context_prompt, load_questions

def test_question_loader():
    questions = load_questions()
    assert isinstance(questions, list)
    assert "question" in questions[0]

def test_prompt_generation():
    data = {
        "country": "Spain",
        "sector": "Healthcare",
        "company_activity": "Private clinic with outpatient services",
        "important_assets": "Medical records",
        "critical_assets": "Clinical server",
        "data_categories": "patient health data",
        "third_party_dependencies": "external laboratory",
        "current_security_operations": "Daily backups",
        "known_gaps": "No formal access review",
        "methodology": "Partial ISO 27001",
        "regulatory_hints": "GDPR",
        "generic": "generic",
        "policy_type": "Access control policy",
        "policy_scope": "Clinical and administrative systems",
        "policy_audience": "Clinic staff",
        "need": "adapt policies to ISO 27001:2022"
    }
    prompt = generate_context_prompt(data)
    assert "Spain" in prompt
    assert "Clinical server" in prompt
    assert "ISO 27001:2022" in prompt
    assert "Security context analysis:" in prompt
    assert "Activity: Private clinic with outpatient services" in prompt
    assert "Data categories: patient health data" in prompt
    assert "Third-party dependencies: external laboratory" in prompt
    assert "Known gaps: No formal access review" in prompt
    assert "Policy type: Access control policy" in prompt
    assert "Scope: Clinical and administrative systems" in prompt
    assert "Audience: Clinic staff" in prompt
    assert "Do not draft the final policy" in prompt


def test_load_questions_uses_questions_config_path_env(monkeypatch, tmp_path):
    questions_config = tmp_path / "context_questions.yaml"
    questions_config.write_text(
        """
questions:
  - id: custom_answer
    question: "Custom question?"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("QUESTIONS_CONFIG_PATH", str(questions_config))

    questions = load_questions()

    assert questions == [{"id": "custom_answer", "question": "Custom question?"}]


def test_generate_context_prompt_uses_questions_config_path_from_app_config(app_context, tmp_path):
    questions_config = tmp_path / "context_questions.yaml"
    questions_config.write_text(
        """
questions:
  - id: custom_answer
    question: "Custom question?"
""",
        encoding="utf-8",
    )
    logic.current_app.config["QUESTIONS_CONFIG_PATH"] = str(questions_config)

    prompt = generate_context_prompt({"custom_answer": "custom value"})

    assert "- Custom question? custom value" in prompt


def test_context_answer_fields_includes_configured_and_runtime_fields(app_context, tmp_path):
    questions_config = tmp_path / "context_questions.yaml"
    questions_config.write_text(
        """
questions:
  - id: custom_answer
    question: "Custom question?"
""",
        encoding="utf-8",
    )

    fields = logic.context_answer_fields(str(questions_config))

    assert "custom_answer" in fields
    assert "company_activity" in fields
    assert "policy_scope" in fields


def test_run_with_agent_uses_config_path_env(monkeypatch):
    captured = {}

    class FakeAgent:
        def create(self, context_id=None):
            captured["context_id"] = context_id

        def run(self, prompt, context_id):
            captured["prompt"] = prompt
            captured["run_context_id"] = context_id
            return "agent output"

    def fake_create_agent_from_config(config_path):
        captured["config_path"] = config_path
        return FakeAgent()

    monkeypatch.setenv("CONFIG_PATH", "/config/custom-context-agent.yaml")
    monkeypatch.setattr(logic, "create_agent_from_config", fake_create_agent_from_config)

    result = logic.run_with_agent("hello", context_id="ctx-1")

    assert result == "agent output"
    assert captured == {
        "config_path": "/config/custom-context-agent.yaml",
        "context_id": "ctx-1",
        "prompt": "hello",
        "run_context_id": "ctx-1",
    }
