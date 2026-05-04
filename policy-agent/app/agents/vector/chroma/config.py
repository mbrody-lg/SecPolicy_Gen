"""Configuration helpers for Chroma-backed RAG components."""

import os


def get_chroma_host(*, default: str = "chroma") -> str:
    """Return a non-empty Chroma host from environment configuration."""
    host = os.getenv("CHROMA_HOST", default).strip()
    if not host:
        raise ValueError("CHROMA_HOST must not be blank.")
    return host


def get_chroma_port(*, default: str = "8000") -> int:
    """Return a bounded Chroma port from environment configuration."""
    raw_port = os.getenv("CHROMA_PORT", default).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("CHROMA_PORT must be an integer port.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("CHROMA_PORT must be between 1 and 65535.")
    return port
