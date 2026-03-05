"""Chroma vector backend client implementation."""

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from flask import current_app

from app.agents.vector.base import VectorClient
from app.agents.vector.chroma.http_client import get_chroma_http_client
        
class ChromaVectorClient(VectorClient):
    """Vector client backed by a Chroma collection."""

    def __init__(self, model):
        """Initialize Chroma client, embedding function, and model reference."""
        super().__init__()
        self.model = model
        self.client = get_chroma_http_client()
        self.embedding_fn = SentenceTransformerEmbeddingFunction(model_name="intfloat/e5-base")
        self.collection = None
        
    def load_collection(self, name: str):
        """Load an existing Chroma collection by name."""
        try:
            self.collection = self.client.get_collection(name)
            return self.collection
        except chromadb.errors.NotFoundError:
            print(f"[WARNING] Collection not found:{name}.")
            return None

    def create_collection(self, name: str, metadata: str):
        """Create a Chroma collection and set it as active."""
        self.collection = self.client.create_collection(name=name, embedding_function=self.embedding_fn, metadata=metadata)
        return self.collection

    def delete_collection(self, name: str):
        """Delete a Chroma collection and clear active handle."""
        self.client.delete_collection(name)
        self.collection = None

    def list_collections(self):
        """List collections available in the connected Chroma backend."""
        return self.client.list_collections()
    
    def search(self, query: str, top_k: int = 3) -> list:
        """Query the active collection and return top document matches."""
        if not query:
            print(f"[WARNING] Undefined query")
        if not self.collection:
            print(f"[WARNING] No collection loaded. Do `load_collection()` first.")
            return []
        
        if current_app.config["DEBUG"]:
            print(f"[ChromaVectorClient] Query: {query}")
            
        results = self.collection.query(query_texts=[query], n_results=top_k)
        documents = results.get("documents", [])
        
        if current_app.config["DEBUG"]:
            print(f"[ChromaVectorClient] Results: {documents[0] if documents else 'No documents found.'}")

        return documents[0] if documents and isinstance(documents[0], list) else []
