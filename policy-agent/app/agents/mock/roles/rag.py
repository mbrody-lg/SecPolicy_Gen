"""Mock RAG retriever role for offline policy-agent tests."""

class MockRAGRetriever:
    """Return a deterministic RAG-like context snippet."""

    def retrieve(self, query: str) -> str:
        """Simulate vector retrieval output for a query string."""
        return f"[MOCK_RAG]: vector query simulation for: '{query}'\nSources: ISO 27001, ISO 27002, GDPR"
