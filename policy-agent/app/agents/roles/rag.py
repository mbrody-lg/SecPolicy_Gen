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

    def apply(self, query: str, top_k: int = 3, retrieval_plan=None) -> str:
        """Return prompt enriched with retrieved context from all clients."""
        evidence_items = []
        search_steps = getattr(retrieval_plan, "steps", None) or []
        if search_steps:
            for step in search_steps:
                for client in self._clients_for_step(step):
                    evidence_items.extend(self._search_client(client, step.query, step.top_k, step=step))
        else:
            for client in self.vector_clients:
                evidence_items.extend(self._search_client(client, query, top_k))

        log_event(
            logger,
            logging.INFO,
            event="policy.rag.search_completed",
            stage="policy_generation",
            result_count=len(evidence_items),
            planned_step_count=len(search_steps),
        )
        if not evidence_items:
            return f"{query}\n\nNo relevant context found."

        context = format_evidence_context(evidence_items)
        enriched_prompt = f"{query}\n\n=== Relevant Context ===\n{context}\n\n=== Relevant Context end ===\n"
        return enriched_prompt

    def _search_client(self, client, query: str, top_k: int, step=None) -> list:
        """Search one vector client and normalize any returned evidence."""
        if current_app.config["DEBUG"]:
            log_event(
                logger,
                logging.DEBUG,
                event="policy.rag.search_started",
                stage="policy_generation",
                client_type=type(client).__name__,
                query_length=len(query),
                top_k=top_k,
                collection=getattr(step, "collection", None),
                family=getattr(step, "family", None),
            )

        search_evidence = getattr(client, "search_evidence", None)
        if callable(search_evidence):
            documents = search_evidence(query, top_k=top_k)
        else:
            documents = client.search(query, top_k=top_k)
        return [
            normalize_evidence(item, fallback_collection=self._client_collection_name(client))
            for item in documents
        ]

    def _clients_for_step(self, step) -> list:
        """Return clients that match the planned collection, with no broad fallback."""
        collection = getattr(step, "collection", None)
        matches = [
            client
            for client in self.vector_clients
            if self._client_collection_name(client) == collection
        ]
        if matches:
            return matches

        log_event(
            logger,
            logging.WARNING,
            event="policy.rag.planned_collection_missing",
            stage="policy_generation",
            collection=collection,
            family=getattr(step, "family", None),
        )
        return []

    @staticmethod
    def _client_collection_name(client) -> str:
        """Best-effort active collection name for routing planned RAG steps."""
        collection = getattr(client, "collection", None)
        name = getattr(collection, "name", None)
        if name:
            return str(name)
        direct_name = getattr(client, "name", None)
        if direct_name:
            return str(direct_name)
        return type(client).__name__
