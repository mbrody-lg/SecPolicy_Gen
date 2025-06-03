import chromadb
from app.agents.vector.base import VectorClient
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from app.agents.vector.chroma.http_client import get_chroma_http_client
from flask import current_app
        
class ChromaVectorClient(VectorClient):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.client = get_chroma_http_client()
        self.embedding_fn = SentenceTransformerEmbeddingFunction(model_name="intfloat/e5-base")
        self.collection = None
        
    def load_collection(self, name: str):
        try:
            self.collection = self.client.get_collection(name)
            return self.collection
        except chromadb.errors.NotFoundError:
            print(f"[WARNING] Collection not found:{name}.")        

    def create_collection(self, name: str, metadata: str):
        self.collection = self.client.create_collection(name=name, embedding_function=self.embedding_fn, metadata=metadata)
        return self.collection

    def delete_collection(self, name: str):
        self.client.delete_collection(name)
        self.collection = None

    def list_collections(self):
        return self.client.list_collections()
    
    def search(self, query: str, top_k: int = 3) -> list:
        if not query:
            print(f"[WARNING] Undefined query")
        if not self.collection:
            print(f"[WARNING] No collection loaded. Do `load_collection()` first.")
            return []
        
        if current_app.config["DEBUG"]:
            print(f"[ChromaVectorClient] Query: {query}")
            
        results = self.collection.query(query_texts=[query], n_results=top_k)
        documents = results.get("documents", [])
        
        if current_app.config["DEBUG"]:
            print(f"[ChromaVectorClient] Results: {documents[0] if documents else 'No documents found.'}")

        return documents[0] if documents and isinstance(documents[0], list) else []
