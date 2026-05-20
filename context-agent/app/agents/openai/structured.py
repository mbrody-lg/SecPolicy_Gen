"""Structured output helpers for OpenAI-backed context-agent calls."""

from __future__ import annotations

import json
from typing import Any


class StructuredOutputError(RuntimeError):
    """Raised when a structured provider call cannot return valid data."""


def _message_value(response: Any) -> Any:
    """Return the first chat completion message from SDK or fake responses."""
    try:
        return response.choices[0].message
    except (AttributeError, IndexError, TypeError) as error:
        raise StructuredOutputError("OpenAI response did not include a message.") from error


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
    temperature: float = 0.2,
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Call chat completions with a strict JSON Schema and return parsed data."""
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
    message = _message_value(response)
    refusal = _message_refusal(message)
    if refusal:
        raise StructuredOutputError("OpenAI structured output was refused.")

    content = _message_content(message)
    if not content.strip():
        raise StructuredOutputError("OpenAI structured output was empty.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise StructuredOutputError("OpenAI structured output was not valid JSON.") from error

    if not isinstance(parsed, dict):
        raise StructuredOutputError("OpenAI structured output must be a JSON object.")
    return parsed
