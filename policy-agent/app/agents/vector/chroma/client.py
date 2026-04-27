"""Chroma vector backend client implementation."""

import logging

import chromadb
from flask import current_app

from app.agents.vector.base import VectorClient
from app.agents.vector.chroma.http_client import get_chroma_http_client
from app.agents.vector.model_loader import LocalSentenceTransformerEmbeddingFunction
from app.observability import log_event

logger = logging.getLogger(__name__)
        
class ChromaVectorClient(VectorClient):
    """Vector client backed by a Chroma collection."""

    def __init__(self, model):
        """Initialize Chroma client, embedding function, and model reference."""
        super().__init__()
        self.model = model
        self.client = get_chroma_http_client()
        self.embedding_fn = LocalSentenceTransformerEmbeddingFunction(model)
        self.collection = None
        
    def load_collection(self, name: str):
        """Load an existing Chroma collection by name."""
        try:
            self.collection = self.client.get_collection(name)
            return self.collection
        except chromadb.errors.NotFoundError:
            log_event(
                logger,
                logging.WARNING,
                event="policy.chroma.collection_missing",
                stage="policy_generation",
                collection=name,
            )
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
        return [item["text"] for item in self.search_evidence(query, top_k=top_k)]

    def search_evidence(self, query: str, top_k: int = 3) -> list:
        """Query the active collection and return structured evidence matches."""
        if not query:
            log_event(
                logger,
                logging.WARNING,
                event="policy.chroma.search_skipped",
                stage="policy_generation",
                reason="empty_query",
            )
            return []
        if not self.collection:
            log_event(
                logger,
                logging.WARNING,
                event="policy.chroma.search_skipped",
                stage="policy_generation",
                reason="missing_collection",
            )
            return []
        
        if current_app.config["DEBUG"]:
            log_event(
                logger,
                logging.DEBUG,
                event="policy.chroma.search_started",
                stage="policy_generation",
                query_length=len(query),
                top_k=top_k,
            )
            
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        ids = results.get("ids", [])
        distances = results.get("distances", [])
        
        if current_app.config["DEBUG"]:
            log_event(
                logger,
                logging.DEBUG,
                event="policy.chroma.search_completed",
                stage="policy_generation",
                result_count=len(documents[0]) if documents and isinstance(documents[0], list) else 0,
            )

        if not documents or not isinstance(documents[0], list):
            return []

        evidence = []
        for index, document in enumerate(documents[0]):
            metadata = metadatas[0][index] if metadatas and metadatas[0] else {}
            evidence.append(
                {
                    "text": document,
                    "id": ids[0][index] if ids and ids[0] else None,
                    "source_id": metadata.get("source_id", "unknown") if isinstance(metadata, dict) else "unknown",
                    "collection": metadata.get("collection", "unknown") if isinstance(metadata, dict) else "unknown",
                    "family": metadata.get("collection_family") if isinstance(metadata, dict) else None,
                    "score": distances[0][index] if distances and distances[0] else None,
                    "metadata": metadata,
                }
            )
        return evidence
