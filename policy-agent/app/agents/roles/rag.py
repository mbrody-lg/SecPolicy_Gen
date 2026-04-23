"""RAG role processor that enriches prompts with vector context."""

import logging

from app.agents.vector.factory import get_vector_clients
from flask import current_app
from app.observability import log_event

logger = logging.getLogger(__name__)

class RAGProcessor:
    """Apply retrieval-augmented generation over configured vector backends."""

    def __init__(self, config: dict):
        """Initialize vector clients and preload configured collections."""
        # Read RAG role configuration from YAML
        vector_config = config.get("vector")
        if not vector_config:
            raise ValueError("The RAG role must contain the 'vector' key with specific configuration.")

        # Create vector clients from YAML configuration
        self.vector_clients = get_vector_clients(vector_config)

        # Load required collections
        self._load_collections(vector_config)

    def _load_collections(self, vector_config):
        """Load vector collections declared in the RAG role configuration."""
        for client, entry in zip(self.vector_clients, vector_config):
            backend_name = next(iter(entry)).lower()
            collections = entry.get("collection", [])

            if not isinstance(collections, list):
                raise ValueError(f"'collection' must be a list for {backend_name}")

            # Load matching collection (one per client)
            if collections:
                client.load_collection(collections[0])  # loads only one collection per client

    def apply(self, query: str, top_k: int = 3) -> str:
        """Return prompt enriched with retrieved context from all clients."""
        results = []
        for client in self.vector_clients:
            if current_app.config["DEBUG"]:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="policy.rag.search_started",
                    stage="policy_generation",
                    client_type=type(client).__name__,
                    query_length=len(query),
                    top_k=top_k,
                )
                
            documents = client.search(query, top_k=top_k)
            results.extend(documents)

        log_event(
            logger,
            logging.INFO,
            event="policy.rag.search_completed",
            stage="policy_generation",
            result_count=len(results),
        )
        if not results:
            return f"{query}\n\nNo relevant context found."

        context = "\n\n".join(results)
        enriched_prompt = f"{query}\n\n=== Relevant Context ===\n{context}\n\n=== Relevant Context end ===\n"
        return enriched_prompt
