"""Singleton HTTP client accessor for Chroma backend connections."""

import os

import chromadb

# Singleton (created only once)
_CLIENT_INSTANCE = None

def get_chroma_http_client():
    """Return a cached Chroma HTTP client instance."""
    global _CLIENT_INSTANCE
    if _CLIENT_INSTANCE is None:
        host = os.getenv("CHROMA_HOST", "chroma")
        port = int(os.getenv("CHROMA_PORT", "8000"))
        _CLIENT_INSTANCE = chromadb.HttpClient(host=host, port=port)
    return _CLIENT_INSTANCE
