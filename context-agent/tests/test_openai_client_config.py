import pytest

from app.agents.openai import client as client_module


class FakeOpenAI:
    include_responses = True

    def __init__(self, *, base_url, api_key, timeout):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.chat = object()
        self.beta = object()
        if self.include_responses:
            self.responses = object()


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
    monkeypatch.setenv("OPENAI_PROVIDER_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OPENAI_STRUCTURED_API_MODE", "responses")
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)

    client = client_module.OpenAIClient()

    assert client.client.api_key == "test-openai-key"
    assert client.client.base_url == "https://openai.example.test/v1"
    assert client.client.timeout == 45.0
    assert client.timeout_seconds == 45.0
    assert client.structured_api_mode == "responses"
    assert client.responses is client.client.responses


def test_openai_client_defaults_to_chat_mode_and_bounded_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENAI_STRUCTURED_API_MODE", raising=False)
    monkeypatch.delenv("OPENAI_PROVIDER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)

    client = client_module.OpenAIClient()

    assert client.structured_api_mode == "chat_completions"
    assert client.timeout_seconds == 180.0
    assert client.client.timeout == 180.0


def test_openai_client_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_PROVIDER_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="OPENAI_PROVIDER_TIMEOUT_SECONDS"):
        client_module.OpenAIClient()


def test_openai_client_rejects_unknown_structured_api_mode(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_STRUCTURED_API_MODE", "assistants")

    with pytest.raises(ValueError, match="OPENAI_STRUCTURED_API_MODE"):
        client_module.OpenAIClient()


def test_openai_client_rejects_responses_mode_without_sdk_support(monkeypatch):
    class FakeOpenAIWithoutResponses(FakeOpenAI):
        include_responses = False

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_STRUCTURED_API_MODE", "responses")
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAIWithoutResponses)

    with pytest.raises(ValueError, match="Responses API support"):
        client_module.OpenAIClient()
