"""OpenAI client wrapper for context-agent roles."""

import os
from urllib.parse import urlparse

from openai import OpenAI

DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/"


def _required_env(name: str) -> str:
    """Read a required provider secret without exposing its value."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set for OpenAI provider execution.")
    return value


def _provider_url(name: str, default: str) -> str:
    """Read and validate a provider base URL."""
    value = os.getenv(name, default).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http(s) URL.")
    return value


class OpenAIClient:
    """Thin wrapper exposing OpenAI chat and beta APIs."""

    def __init__(self):
        """Initialize OpenAI SDK client from environment variables."""
        self.client = OpenAI(
            base_url=_provider_url("OPENAI_API_URL", DEFAULT_OPENAI_API_URL),
            api_key=_required_env("OPENAI_API_KEY")
        )
        self.chat = self.client.chat
        self.beta = self.client.beta
