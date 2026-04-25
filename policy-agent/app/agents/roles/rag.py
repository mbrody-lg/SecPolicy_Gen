"""RAG role processor that enriches prompts with vector context."""

import logging

from app.agents.vector.factory import get_vector_clients
from flask import current_app
from app.observability import log_event
from app.rag.evidence import format_evidence_context, normalize_evidence

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

    def apply(self, query: str, top_k: int = 3) -> str:
        """Return prompt enriched with retrieved context from all clients."""
        evidence_items = []
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
                
            search_evidence = getattr(client, "search_evidence", None)
            if callable(search_evidence):
                documents = search_evidence(query, top_k=top_k)
            else:
                documents = client.search(query, top_k=top_k)
            evidence_items.extend(
                normalize_evidence(item, fallback_collection=type(client).__name__)
                for item in documents
            )

        log_event(
            logger,
            logging.INFO,
            event="policy.rag.search_completed",
            stage="policy_generation",
            result_count=len(evidence_items),
        )
        if not evidence_items:
            return f"{query}\n\nNo relevant context found."

        context = format_evidence_context(evidence_items)
        enriched_prompt = f"{query}\n\n=== Relevant Context ===\n{context}\n\n=== Relevant Context end ===\n"
        return enriched_prompt
