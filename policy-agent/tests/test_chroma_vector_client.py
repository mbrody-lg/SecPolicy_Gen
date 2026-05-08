import importlib
import sys
from types import SimpleNamespace


class FakeModel:
    def encode(self, texts, normalize_embeddings=True):
        return [[0.1, 0.2] for _ in texts]


def test_load_collection_uses_configured_embedding_function(monkeypatch):
    fake_chromadb = SimpleNamespace(errors=SimpleNamespace(NotFoundError=RuntimeError))
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    chroma_client = importlib.import_module("app.agents.vector.chroma.client")

    captured = {}

    class FakeChromaClient:
        def get_collection(self, name, embedding_function=None):
            captured["name"] = name
            captured["embedding_function"] = embedding_function
            return SimpleNamespace(name=name)

    monkeypatch.setattr(chroma_client, "get_chroma_http_client", lambda: FakeChromaClient())

    client = chroma_client.ChromaVectorClient(model=FakeModel())
    collection = client.load_collection("normativa")

    assert collection.name == "normativa"
    assert captured["name"] == "normativa"
    assert captured["embedding_function"] is client.embedding_fn
