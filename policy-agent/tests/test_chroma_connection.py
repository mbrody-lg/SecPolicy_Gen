from app.agents.vector.chroma.http_client import get_chroma_http_client

def test_chroma_http_client_connection():
    client = get_chroma_http_client()
    collections = client.list_collections()
    
    assert isinstance(collections, list)
    print("Chroma is active. Available collections:", [c.name for c in collections])
