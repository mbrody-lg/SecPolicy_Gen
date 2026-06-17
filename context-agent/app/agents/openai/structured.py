"""Structured output helpers for OpenAI-backed context-agent calls."""

from __future__ import annotations

from dataclasses import dataclass
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
        api_mode: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message or self.safe_message)
        self.phase = phase
        self.schema_name = schema_name
        self.model = model
        self.api_mode = api_mode or self.api_mode
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


@dataclass(frozen=True)
class ProviderRequest:
    """Provider-domain contract for one structured Context Agent phase call."""

    model: str
    messages: list[dict[str, str]]
    schema_name: str
    json_schema: dict[str, Any]
    phase: str | None = None
    temperature: float = 0.2
    max_tokens: int = 4000
    api_mode: str = "chat_completions"
    store: bool = False
    background: bool = False

    def __post_init__(self) -> None:
        """Validate provider-neutral request invariants."""
        if self.api_mode not in {"chat_completions", "responses"}:
            raise ValueError("api_mode must be chat_completions or responses.")
        if self.store:
            raise ValueError("Structured Context Agent calls must use store=false.")
        if self.background:
            raise ValueError("Structured Context Agent calls must use background=false.")
        if not self.schema_name:
            raise ValueError("schema_name is required.")
        if not isinstance(self.json_schema, dict):
            raise ValueError("json_schema must be a dictionary.")
        if not self.messages:
            raise ValueError("messages are required.")


def _provider_exception_to_error(
    error: Exception,
    *,
    phase: str | None,
    schema_name: str,
    model: str | None,
    api_mode: str = "chat_completions",
) -> ProviderCallError:
    """Map SDK/network exceptions to bounded provider errors."""
    status_code = getattr(error, "status_code", None)
    error_name = error.__class__.__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in error_name:
        return ProviderTimeoutError(
            phase=phase,
            schema_name=schema_name,
            model=model,
            api_mode=api_mode,
        )
    if status_code == 429 or "ratelimit" in error_name or "rate_limit" in error_name:
        return ProviderRateLimitError(
            phase=phase,
            schema_name=schema_name,
            model=model,
            api_mode=api_mode,
        )
    return ProviderConnectivityError(
        phase=phase,
        schema_name=schema_name,
        model=model,
        api_mode=api_mode,
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


def _parse_json_content(
    content: str,
    *,
    phase: str | None,
    schema_name: str,
    model: str | None,
) -> dict[str, Any]:
    """Parse provider JSON text into the expected top-level object."""
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


def _create_structured_chat_completion(*, chat: Any, request: ProviderRequest) -> dict[str, Any]:
    """Call Chat Completions with a strict JSON Schema and return parsed data."""
    try:
        response = chat.completions.create(
            model=request.model,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": request.json_schema,
                    "strict": True,
                },
            },
        )
    except ProviderCallError:
        raise
    except Exception as error:
        raise _provider_exception_to_error(
            error,
            phase=request.phase,
            schema_name=request.schema_name,
            model=request.model,
            api_mode=request.api_mode,
        ) from error

    message = _message_value(
        response,
        phase=request.phase,
        schema_name=request.schema_name,
        model=request.model,
    )
    refusal = _message_refusal(message)
    if refusal:
        raise ProviderRefusalError(
            phase=request.phase,
            schema_name=request.schema_name,
            model=request.model,
        )

    return _parse_json_content(
        _message_content(message),
        phase=request.phase,
        schema_name=request.schema_name,
        model=request.model,
    )


def _response_output_refusal(response: Any) -> str:
    """Return a refusal from a Responses API output item when present."""
    for output in getattr(response, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for item in getattr(output, "content", []) or []:
            if getattr(item, "type", None) == "refusal":
                return str(getattr(item, "refusal", "") or "")
    return ""


def _incomplete_reason(response: Any) -> str | None:
    """Return a bounded incomplete reason from Responses API output."""
    details = getattr(response, "incomplete_details", None)
    if isinstance(details, dict):
        return str(details.get("reason") or "") or None
    return str(getattr(details, "reason", "") or "") or None


def _create_structured_response(*, responses: Any, request: ProviderRequest) -> dict[str, Any]:
    """Call Responses API with strict JSON Schema and return parsed data."""
    if responses is None:
        raise ProviderConnectivityError(
            phase=request.phase,
            schema_name=request.schema_name,
            model=request.model,
            api_mode=request.api_mode,
            details={"exception_class": "ResponsesClientUnavailable"},
        )
    try:
        response = responses.create(
            model=request.model,
            input=request.messages,
            temperature=request.temperature,
            max_output_tokens=request.max_tokens,
            store=request.store,
            background=request.background,
            text={
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "schema": request.json_schema,
                    "strict": True,
                },
            },
        )
    except ProviderCallError:
        raise
    except Exception as error:
        raise _provider_exception_to_error(
            error,
            phase=request.phase,
            schema_name=request.schema_name,
            model=request.model,
            api_mode=request.api_mode,
        ) from error

    if _response_output_refusal(response):
        raise ProviderRefusalError(
            phase=request.phase,
            schema_name=request.schema_name,
            model=request.model,
            api_mode=request.api_mode,
        )
    if getattr(response, "status", "completed") != "completed":
        raise ProviderIncompleteError(
            phase=request.phase,
            schema_name=request.schema_name,
            model=request.model,
            api_mode=request.api_mode,
            details={"reason": _incomplete_reason(response) or "unknown"},
        )
    return _parse_json_content(
        str(getattr(response, "output_text", "") or ""),
        phase=request.phase,
        schema_name=request.schema_name,
        model=request.model,
    )


def create_structured_provider_call(
    *,
    chat: Any = None,
    responses: Any = None,
    request: ProviderRequest,
) -> dict[str, Any]:
    """Execute a structured provider request through the configured API mode."""
    if request.api_mode == "responses":
        return _create_structured_response(responses=responses, request=request)
    return _create_structured_chat_completion(chat=chat, request=request)


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
    """Backward-compatible Chat Completions wrapper for existing callers."""
    request = ProviderRequest(
        model=model,
        messages=messages,
        schema_name=schema_name,
        json_schema=json_schema,
        phase=phase,
        temperature=temperature,
        max_tokens=max_tokens,
        api_mode="chat_completions",
    )
    return create_structured_provider_call(chat=chat, request=request)
