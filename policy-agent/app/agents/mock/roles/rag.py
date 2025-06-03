class MockRAGRetriever:
    def retrieve(self, query: str) -> str:
        return f"[MOCK_RAG]: vector query simulation for: '{query}'\nSources: ISO 27001, ISO 27002, GDPR"