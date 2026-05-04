import pytest

from app.agents.mistralai import client as mistral_client_module
from app.agents.openai import client as openai_client_module


class FakeOpenAI:
    def __init__(self, *, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = object()


class FakeMistral:
    def __init__(self, *, api_key, server_url):
        self.api_key = api_key
        self.server_url = server_url
        self.chat = object()


def test_openai_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY must be set"):
        openai_client_module.OpenAIClient()


def test_openai_client_rejects_malformed_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_URL", "api.openai.local")

    with pytest.raises(ValueError, match="OPENAI_API_URL must be an http"):
        openai_client_module.OpenAIClient()


def test_openai_client_uses_configured_provider_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_URL", "https://openai.example.test/v1")
    monkeypatch.setattr(openai_client_module, "OpenAI", FakeOpenAI)

    client = openai_client_module.OpenAIClient()

    assert client.client.api_key == "test-openai-key"
    assert client.client.base_url == "https://openai.example.test/v1"


def test_mistral_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    with pytest.raises(ValueError, match="MISTRAL_API_KEY must be set"):
        mistral_client_module.MistralClient()


def test_mistral_client_rejects_malformed_base_url(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("MISTRAL_API_URL", "api.mistral.local")

    with pytest.raises(ValueError, match="MISTRAL_API_URL must be an http"):
        mistral_client_module.MistralClient()


def test_mistral_client_uses_configured_provider_values(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("MISTRAL_API_URL", "https://mistral.example.test/v1")
    monkeypatch.setattr(mistral_client_module, "Mistral", FakeMistral)

    client = mistral_client_module.MistralClient()

    assert client.client.api_key == "test-mistral-key"
    assert client.client.server_url == "https://mistral.example.test/v1"
