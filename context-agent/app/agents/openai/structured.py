"""Structured output helpers for OpenAI-backed context-agent calls."""

from __future__ import annotations

import json
from typing import Any


class ProviderCallError(RuntimeError):
    """Base error for bounded provider-call failures."""

    error_type = "provider_error"
    error_code = "provider_error"
    retryable = False
    status_code = 502
    safe_message = "OpenAI provider call failed."
    provider = "openai"
    api_mode = "chat_completions"

    def __init__(
        self,
        message: str | None = None,
        *,
        phase: str | None = None,
        schema_name: str | None = None,
        model: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message or self.safe_message)
        self.phase = phase
        self.schema_name = schema_name
        self.model = model
        self.details = details or {}

    def to_diagnostic(self) -> dict[str, Any]:
        """Return safe diagnostic metadata without provider payloads."""
        return {
            "provider": self.provider,
            "api_mode": self.api_mode,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "safe_message": self.safe_message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "phase": self.phase,
            "schema_name": self.schema_name,
            "model": self.model,
            "details": self.details,
        }


class ProviderRefusalError(ProviderCallError):
    """Raised when the provider explicitly refuses a structured request."""

    error_type = "provider_refusal"
    error_code = "openai_refusal"
    status_code = 422
    safe_message = "OpenAI refused the structured output request."


class ProviderIncompleteError(ProviderCallError):
    """Raised when the provider response is incomplete or empty."""

    error_type = "provider_incomplete"
    error_code = "openai_incomplete_response"
    retryable = True
    safe_message = "OpenAI returned an incomplete structured output response."


class ProviderSchemaMismatchError(ProviderCallError):
    """Raised when the provider output cannot be parsed as the expected shape."""

    error_type = "provider_schema_mismatch"
    error_code = "openai_schema_mismatch"
    safe_message = "OpenAI structured output did not match the expected schema."


class ProviderTimeoutError(ProviderCallError):
    """Raised when the provider call times out."""

    error_type = "provider_timeout"
    error_code = "openai_timeout"
    retryable = True
    status_code = 504
    safe_message = "OpenAI structured output request timed out."


class ProviderRateLimitError(ProviderCallError):
    """Raised when the provider reports rate limiting."""

    error_type = "provider_rate_limit"
    error_code = "openai_rate_limit"
    retryable = True
    status_code = 429
    safe_message = "OpenAI structured output request was rate limited."


class ProviderConnectivityError(ProviderCallError):
    """Raised when the provider call fails before returning a usable response."""

    error_type = "provider_connectivity"
    error_code = "openai_connectivity_error"
    retryable = True
    safe_message = "OpenAI structured output request failed before a response was available."


# Backward-compatible import name from the first structured-output slice.
StructuredOutputError = ProviderCallError


def _provider_exception_to_error(
    error: Exception,
    *,
    phase: str | None,
    schema_name: str,
    model: str | None,
) -> ProviderCallError:
    """Map SDK/network exceptions to bounded provider errors."""
    status_code = getattr(error, "status_code", None)
    error_name = error.__class__.__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in error_name:
        return ProviderTimeoutError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        )
    if status_code == 429 or "ratelimit" in error_name or "rate_limit" in error_name:
        return ProviderRateLimitError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        )
    return ProviderConnectivityError(
        phase=phase,
        schema_name=schema_name,
        model=model,
        details={"exception_class": error.__class__.__name__},
    )


def _message_value(
    response: Any,
    *,
    phase: str | None,
    schema_name: str,
    model: str | None,
) -> Any:
    """Return the first chat completion message from SDK or fake responses."""
    try:
        return response.choices[0].message
    except (AttributeError, IndexError, TypeError) as error:
        raise ProviderIncompleteError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        ) from error


def _message_content(message: Any) -> str:
    """Return message content from SDK objects or dict-like fakes."""
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _message_refusal(message: Any) -> str:
    """Return a provider refusal reason when exposed by the SDK."""
    if isinstance(message, dict):
        return str(message.get("refusal") or "")
    return str(getattr(message, "refusal", "") or "")


def create_structured_chat_completion(
    *,
    chat: Any,
    model: str,
    messages: list[dict[str, str]],
    schema_name: str,
    json_schema: dict[str, Any],
    phase: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Call chat completions with a strict JSON Schema and return parsed data."""
    try:
        response = chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                },
            },
        )
    except ProviderCallError:
        raise
    except Exception as error:
        raise _provider_exception_to_error(
            error,
            phase=phase,
            schema_name=schema_name,
            model=model,
        ) from error

    message = _message_value(response, phase=phase, schema_name=schema_name, model=model)
    refusal = _message_refusal(message)
    if refusal:
        raise ProviderRefusalError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        )

    content = _message_content(message)
    if not content.strip():
        raise ProviderIncompleteError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        )

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ProviderSchemaMismatchError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        ) from error

    if not isinstance(parsed, dict):
        raise ProviderSchemaMismatchError(
            phase=phase,
            schema_name=schema_name,
            model=model,
        )
    return parsed
