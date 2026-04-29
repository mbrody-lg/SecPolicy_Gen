from app.agents.roles import rag as rag_module
from app.rag.planner import RetrievalPlan, RetrievalPlanStep


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
    assert "citation=normativa:legacy" in enriched_prompt
    assert "normativa document" in enriched_prompt
    assert "sector document" in enriched_prompt
    assert "guia document" in enriched_prompt


def test_rag_processor_prefers_structured_evidence_when_available(app_context, monkeypatch):
    class StructuredSearchClient(FakeSearchClient):
        def search_evidence(self, query, top_k=3):
            self.queries.append((query, top_k))
            return [
                {
                    "text": "GDPR requires appropriate security controls.",
                    "id": "normativa:rgpd:chunk-1",
                    "source_id": "normativa",
                    "collection": "normativa",
                    "family": "legal_norms",
                    "score": 0.15,
                    "metadata": {"source_doc": "RGPD.pdf"},
                }
            ]

    client = StructuredSearchClient("normativa")
    monkeypatch.setattr(rag_module, "get_vector_clients", lambda vector_config: [client])

    processor = rag_module.RAGProcessor(
        {
            "vector": [
                {
                    "chroma": "Chroma Vector Database",
                    "collection": ["normativa"],
                    "model": "test-model",
                }
            ]
        }
    )

    enriched_prompt = processor.apply("protect personal data", top_k=4)

    assert client.queries == [("protect personal data", 4)]
    assert "citation=normativa:normativa:rgpd:chunk-1" in enriched_prompt
    assert "family=legal_norms" in enriched_prompt
    assert "GDPR requires appropriate security controls." in enriched_prompt


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


def test_rag_processor_uses_retrieval_plan_for_collection_queries(app_context, monkeypatch):
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
    plan = RetrievalPlan(
        context_id="ctx-health",
        required_families=["legal_norms", "sector_norms"],
        steps=[
            RetrievalPlanStep(
                family="legal_norms",
                collection="normativa",
                query="legal_norms: protect patient data",
                top_k=4,
            ),
            RetrievalPlanStep(
                family="sector_norms",
                collection="sector",
                query="sector_norms: protect patient data",
                top_k=3,
            ),
        ],
    )

    enriched_prompt = processor.apply("original prompt", retrieval_plan=plan)

    assert clients[0].queries == [("legal_norms: protect patient data", 4)]
    assert clients[1].queries == [("sector_norms: protect patient data", 3)]
    assert clients[2].queries == []
    assert "normativa document" in enriched_prompt
    assert "sector document" in enriched_prompt
