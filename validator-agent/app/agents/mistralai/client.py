"""Mistral API client wrapper for validator-agent backends."""

import os
from urllib.parse import urlparse

from mistralai.client import Mistral

DEFAULT_MISTRAL_API_URL = "https://api.mistral.ai/v1"


def _required_env(name: str) -> str:
    """Read a required provider secret without exposing its value."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set for Mistral provider execution.")
    return value


def _provider_url(name: str, default: str) -> str:
    """Read and validate a provider base URL."""
    value = os.getenv(name, default).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http(s) URL.")
    return value


class MistralClient:
    """Provide configured Mistral chat API access."""

    def __init__(self):
        """Initialize Mistral SDK client using environment configuration."""
        self.api_key = _required_env("MISTRAL_API_KEY")
        self.base_url = _provider_url("MISTRAL_API_URL", DEFAULT_MISTRAL_API_URL)
        self.client = Mistral(api_key=self.api_key, server_url=self.base_url)
        

    def chat(self, model: str, prompt: str, instructions: str, temperature: float, max_tokens: int):
        """Execute a chat completion call against the configured Mistral model."""
        response = self.client.chat.complete(
            model = model,
            messages = [
                {
                    "role": "system",
                    "content": instructions
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature = temperature,
            max_tokens = max_tokens
        )
        return response
