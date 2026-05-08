from app.agents.vector import factory
from app.agents.vector.base import VECTOR_CLIENT_REGISTRY, VectorClient


class FakeVectorClient(VectorClient):
    loaded_collections = []

    def __init__(self, model):
        self.model = model
        self.loaded_collection = None

    def load_collection(self, name):
        self.loaded_collection = name
        self.loaded_collections.append(name)

    def search(self, query: str, top_k: int = 3):
        return [f"{self.loaded_collection}:{query}:{top_k}"]


def test_get_vector_clients_expands_all_collections(monkeypatch):
    FakeVectorClient.loaded_collections = []
    monkeypatch.setitem(VECTOR_CLIENT_REGISTRY, "fake", FakeVectorClient)
    monkeypatch.setattr(factory, "import_all_vector_modules", lambda module_name: None)
    monkeypatch.setattr(factory, "download_model_if_needed", lambda model_id, revision=None: None)
    monkeypatch.setattr(
        factory,
        "load_model",
        lambda model_id, revision=None: f"model:{model_id}:{revision}",
    )

    clients = factory.get_vector_clients(
        [
            {
                "fake": "Fake Vector Database",
                "collection": ["legal_norms", "sector_norms", "implementation_guides"],
                "model": "test-model",
                "revision": "test-revision",
            }
        ]
    )

    assert [client.loaded_collection for client in clients] == [
        "legal_norms",
        "sector_norms",
        "implementation_guides",
    ]
    assert FakeVectorClient.loaded_collections == ["legal_norms", "sector_norms", "implementation_guides"]
    assert all(client.model == "model:test-model:test-revision" for client in clients)


def test_get_vector_clients_keeps_collections_from_multiple_entries(monkeypatch):
    FakeVectorClient.loaded_collections = []
    monkeypatch.setitem(VECTOR_CLIENT_REGISTRY, "fake", FakeVectorClient)
    monkeypatch.setattr(factory, "import_all_vector_modules", lambda module_name: None)
    monkeypatch.setattr(factory, "download_model_if_needed", lambda model_id, revision=None: None)
    monkeypatch.setattr(factory, "load_model", lambda model_id, revision=None: f"model:{model_id}")

    clients = factory.get_vector_clients(
        [
            {
                "fake": "Fake Vector Database",
                "collection": ["legal_norms"],
                "model": "model-a",
            },
            {
                "fake": "Fake Vector Database",
                "collection": ["sector_norms", "implementation_guides"],
                "model": "model-b",
            },
        ]
    )

    assert [client.loaded_collection for client in clients] == [
        "legal_norms",
        "sector_norms",
        "implementation_guides",
    ]
    assert [client.model for client in clients] == [
        "model:model-a",
        "model:model-b",
        "model:model-b",
    ]
