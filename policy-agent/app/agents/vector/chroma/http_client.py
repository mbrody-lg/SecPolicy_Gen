"""Singleton HTTP client accessor for Chroma backend connections."""

import chromadb

from app.agents.vector.chroma.config import get_chroma_host, get_chroma_port

# Singleton (created only once)
_CLIENT_INSTANCE = None


def get_chroma_http_client():
    """Return a cached Chroma HTTP client instance."""
    global _CLIENT_INSTANCE
    if _CLIENT_INSTANCE is None:
        host = get_chroma_host(default="chroma")
        port = get_chroma_port(default="8000")
        _CLIENT_INSTANCE = chromadb.HttpClient(host=host, port=port)
    return _CLIENT_INSTANCE
