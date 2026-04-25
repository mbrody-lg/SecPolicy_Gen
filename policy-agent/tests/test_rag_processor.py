from app.agents.roles import rag as rag_module


class FakeSearchClient:
    def __init__(self, name):
        self.name = name
        self.queries = []

    def search(self, query, top_k=3):
        self.queries.append((query, top_k))
        return [f"{self.name} document"]


def test_rag_processor_queries_each_configured_client(app_context, monkeypatch):
    clients = [
        FakeSearchClient("normativa"),
        FakeSearchClient("sector"),
        FakeSearchClient("guia"),
    ]
    monkeypatch.setattr(rag_module, "get_vector_clients", lambda vector_config: clients)

    processor = rag_module.RAGProcessor(
        {
            "vector": [
                {
                    "chroma": "Chroma Vector Database",
                    "collection": ["normativa", "sector", "guia"],
                    "model": "test-model",
                }
            ]
        }
    )

    enriched_prompt = processor.apply("protect patient data", top_k=2)

    assert [client.queries for client in clients] == [
        [("protect patient data", 2)],
        [("protect patient data", 2)],
        [("protect patient data", 2)],
    ]
    assert "=== Relevant Context ===" in enriched_prompt
    assert "normativa document" in enriched_prompt
    assert "sector document" in enriched_prompt
    assert "guia document" in enriched_prompt


def test_rag_processor_keeps_empty_result_fallback(app_context, monkeypatch):
    class EmptySearchClient(FakeSearchClient):
        def search(self, query, top_k=3):
            self.queries.append((query, top_k))
            return []

    monkeypatch.setattr(rag_module, "get_vector_clients", lambda vector_config: [EmptySearchClient("empty")])

    processor = rag_module.RAGProcessor(
        {
            "vector": [
                {
                    "chroma": "Chroma Vector Database",
                    "collection": ["empty"],
                    "model": "test-model",
                }
            ]
        }
    )

    assert processor.apply("no matches") == "no matches\n\nNo relevant context found."
