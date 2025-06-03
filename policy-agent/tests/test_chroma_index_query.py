from app.agents.vector.chroma.http_client import get_chroma_http_client
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

def test_chroma_index_and_query():
    model_id = "intfloat/e5-base"
    embed_fn = SentenceTransformerEmbeddingFunction(model_name=model_id)

    client = get_chroma_http_client()
    collection = client.get_or_create_collection(name="test_collection", embedding_function=embed_fn)

    # Documents d'exemple
    docs = ["ISO 27001 establishes controls to protect information.",
            "The GDPR regulates the processing of personal data."]
    ids = ["doc1", "doc2"]

    collection.add(documents=docs, ids=ids)

    results = collection.query(query_texts=["protecció dades"], n_results=2)

    assert "documents" in results
    assert isinstance(results["documents"][0], list)
    print("Resultats:", results["documents"][0])
