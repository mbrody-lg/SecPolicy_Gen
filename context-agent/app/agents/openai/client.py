"""OpenAI client wrapper for context-agent roles."""

import os
from urllib.parse import urlparse

from openai import OpenAI

DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/"
DEFAULT_OPENAI_PROVIDER_TIMEOUT_SECONDS = 180.0
OPENAI_STRUCTURED_API_MODES = {"chat_completions", "responses"}


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


def _provider_timeout(name: str, default: float) -> float:
    """Read and validate a positive provider timeout."""
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return value


def _structured_api_mode(name: str = "OPENAI_STRUCTURED_API_MODE") -> str:
    """Return the configured OpenAI structured-output API mode."""
    value = os.getenv(name, "chat_completions").strip().lower()
    if value not in OPENAI_STRUCTURED_API_MODES:
        allowed = ", ".join(sorted(OPENAI_STRUCTURED_API_MODES))
        raise ValueError(f"{name} must be one of: {allowed}.")
    return value


class OpenAIClient:
    """Thin wrapper exposing OpenAI chat and beta APIs."""

    def __init__(self):
        """Initialize OpenAI SDK client from environment variables."""
        self.timeout_seconds = _provider_timeout(
            "OPENAI_PROVIDER_TIMEOUT_SECONDS",
            DEFAULT_OPENAI_PROVIDER_TIMEOUT_SECONDS,
        )
        self.structured_api_mode = _structured_api_mode()
        self.client = OpenAI(
            base_url=_provider_url("OPENAI_API_URL", DEFAULT_OPENAI_API_URL),
            api_key=_required_env("OPENAI_API_KEY"),
            timeout=self.timeout_seconds,
        )
        self.chat = self.client.chat
        self.beta = self.client.beta
        self.responses = getattr(self.client, "responses", None)
        if self.structured_api_mode == "responses" and self.responses is None:
            raise ValueError(
                "OPENAI_STRUCTURED_API_MODE=responses requires an OpenAI SDK "
                "client with Responses API support."
            )
