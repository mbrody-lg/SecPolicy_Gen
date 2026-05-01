import pytest

from app.agents.openai import client as client_module


class FakeOpenAI:
    def __init__(self, *, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = object()
        self.beta = object()


def test_openai_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY must be set"):
        client_module.OpenAIClient()


def test_openai_client_rejects_malformed_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_URL", "api.openai.local")

    with pytest.raises(ValueError, match="OPENAI_API_URL must be an http"):
        client_module.OpenAIClient()


def test_openai_client_uses_configured_provider_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_URL", "https://openai.example.test/v1")
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)

    client = client_module.OpenAIClient()

    assert client.client.api_key == "test-openai-key"
    assert client.client.base_url == "https://openai.example.test/v1"
