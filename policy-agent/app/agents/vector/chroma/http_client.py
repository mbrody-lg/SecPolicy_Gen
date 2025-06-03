import chromadb
import os

# Singleton (es crea una sola vegada)
_client_instance = None

def get_chroma_http_client():
    global _client_instance
    if _client_instance is None:
        host = os.getenv("CHROMA_HOST", "chroma")
        port = int(os.getenv("CHROMA_PORT", "8000"))
        _client_instance = chromadb.HttpClient(host=host, port=port)
    return _client_instance
