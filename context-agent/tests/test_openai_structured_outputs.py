import json
from types import SimpleNamespace

import pytest

from app.agents import factory
from app.agents.base import AGENT_REGISTRY
from app.agents.openai import client as client_module
from app.agents.openai.roles.optimiser import PromptResponseOptimiser
from app.agents.openai.roles.proactive import ProactiveGoalCreator
from app.agents.openai.structured import (
    StructuredOutputError,
    create_structured_chat_completion,
)


class FakeCompletions:
    def __init__(self, payload=None, *, refusal=None, content=None):
        self.payload = payload or {}
        self.refusal = refusal
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.content if self.content is not None else json.dumps(self.payload)
        message = SimpleNamespace(content=content, refusal=self.refusal)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAI:
    completions = FakeCompletions()

    def __init__(self, *, base_url, api_key):
        self.chat = FakeChat(self.completions)
        self.beta = SimpleNamespace()
        self.base_url = base_url
        self.api_key = api_key


def install_fake_openai(monkeypatch, completions):
    FakeOpenAI.completions = completions
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_URL", "https://openai.example.test/v1")
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)


def test_structured_chat_completion_sends_strict_json_schema():
    completions = FakeCompletions({"answer": "ok"})

    result = create_structured_chat_completion(
        chat=FakeChat(completions),
        model="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        schema_name="test_schema",
        json_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )

    assert result == {"answer": "ok"}
    call = completions.calls[0]
    assert call["model"] == "gpt-test"
    assert call["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


def test_structured_chat_completion_rejects_refusal():
    completions = FakeCompletions(refusal="not allowed")

    with pytest.raises(StructuredOutputError, match="refused"):
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )


def test_proactive_goal_creator_uses_configured_model_instructions_and_schema(monkeypatch):
    completions = FakeCompletions({
        "improved_prompt": "Phase: PLANNING\nImproved prompt",
        "workflow_phase": "PLANNING",
        "preserved_constraints": ["Do not draft a policy"],
    })
    install_fake_openai(monkeypatch, completions)

    role = ProactiveGoalCreator(
        model="gpt-configured",
        instructions="CUSTOM PROACTIVE INSTRUCTIONS",
    )
    result = role.execute("Phase: PLANNING\nInput")

    assert result == "Phase: PLANNING\nImproved prompt"
    call = completions.calls[0]
    assert call["model"] == "gpt-configured"
    assert call["messages"][0] == {
        "role": "system",
        "content": "CUSTOM PROACTIVE INSTRUCTIONS",
    }
    assert call["response_format"]["json_schema"]["name"] == "context_agent_proactive_prompt"
    assert "improved_prompt" in call["response_format"]["json_schema"]["schema"]["required"]


def test_response_optimiser_uses_configured_model_instructions_and_schema(monkeypatch):
    completions = FakeCompletions({
        "improved_response": "Structured final context",
        "workflow_phase": "POLICY_HANDOFF",
        "preserved_constraints": ["Preserve facts"],
        "context_tags": ["[context:regulation]GDPR"],
    })
    install_fake_openai(monkeypatch, completions)

    role = PromptResponseOptimiser(
        model="gpt-configured",
        instructions="CUSTOM OPTIMISER INSTRUCTIONS",
    )
    result = role.execute("Original prompt", "Raw response")

    assert result == "Structured final context"
    call = completions.calls[0]
    assert call["model"] == "gpt-configured"
    assert call["messages"][0] == {
        "role": "system",
        "content": "CUSTOM OPTIMISER INSTRUCTIONS",
    }
    assert call["response_format"]["json_schema"]["name"] == "context_agent_optimised_response"
    assert "improved_response" in call["response_format"]["json_schema"]["schema"]["required"]


def test_factory_passes_role_instructions_when_backend_accepts_them(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    config = tmp_path / "context_agent.yaml"
    config.write_text(
        """
name: context-agent
type: fake
instructions: Assistant instructions
model: gpt-configured
tools: []
role_instructions:
  proactive_goal_creator: YAML proactive
  response_optimiser: YAML optimiser
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(factory.importlib, "import_module", lambda module_path: None)
    monkeypatch.setitem(AGENT_REGISTRY, "fake", FakeAgent)

    factory.create_agent_from_config(str(config))

    assert captured["instructions"] == "Assistant instructions"
    assert captured["model"] == "gpt-configured"
    assert captured["role_instructions"] == {
        "proactive_goal_creator": "YAML proactive",
        "response_optimiser": "YAML optimiser",
    }
