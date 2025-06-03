from app.agents.vector.factory import get_vector_clients
from flask import current_app

class RAGProcessor:
    def __init__(self, config: dict):
        # Llegeix la configuració del YAML del rol RAG
        vector_config = config.get("vector")
        if not vector_config:
            raise ValueError("The RAG role must contain the 'vector' key with specific configuration.")

        # Crea tots els clients vectorials segons la definició del YAML
        self.vector_clients = get_vector_clients(vector_config)

        # Carrega les col·leccions necessàries
        self._load_collections(vector_config)

    def _load_collections(self, vector_config):
        for client, entry in zip(self.vector_clients, vector_config):
            backend_name = next(iter(entry)).lower()
            collections = entry.get("collection", [])

            if not isinstance(collections, list):
                raise ValueError(f"'collection' must be a list for {backend_name}")

            # Carreguem la col·lecció corresponent (una per client)
            if collections:
                client.load_collection(collections[0])  # només en carrega una per client

    def apply(self, query: str, top_k: int = 3) -> str:
        results = []
        for client in self.vector_clients:
            
            if current_app.config["DEBUG"]:
                print(f"[DEBUG] Client: {client}, type: {type(client)}, callable search: {hasattr(client, 'search')}")
                print(f"[DEBUG] Query: {query}")
                
            documents = client.search(query, top_k=top_k)
            results.extend(documents)

        if not results:
            return f"{query}\n\nNo relevant context found."

        context = "\n\n".join(results)
        enriched_prompt = f"{query}\n\n=== Relevant Context ===\n{context}\n\n=== Relevant Context end ===\n"
        return enriched_prompt
