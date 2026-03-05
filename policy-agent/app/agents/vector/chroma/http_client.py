import os

import chromadb

# Singleton (es crea una sola vegada)
_CLIENT_INSTANCE = None

def get_chroma_http_client():
    global _CLIENT_INSTANCE
    if _CLIENT_INSTANCE is None:
        host = os.getenv("CHROMA_HOST", "chroma")
        port = int(os.getenv("CHROMA_PORT", "8000"))
        _CLIENT_INSTANCE = chromadb.HttpClient(host=host, port=port)
    return _CLIENT_INSTANCE
