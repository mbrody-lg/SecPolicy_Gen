import os
import yaml
from pathlib import Path
from pypdf import PdfReader
from tqdm import tqdm
from dotenv import load_dotenv
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from sentence_transformers import SentenceTransformer
from app.agents.vector.model_loader import download_model_if_needed, load_model

def extract_text_from_pdf(path):
    reader = PdfReader(path)
    return "".join(page.extract_text() or "" for page in reader.pages)

def chunk_text(text, size, overlap):
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        start += size - overlap
    return chunks

def load_config_from_policy_yaml():
    path = os.getenv("CONFIG_PATH", "/config/policy_agent.yaml")
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    vector_roles = []

    for role in data.get("roles", []):
        if "RAG" in role and "vector" in role:
            for entry in role["vector"]:
                if "chroma" in entry:
                    collections = entry.get("collection", [])
                    model = entry.get("model")
                    chunk_size = entry.get("chunk_size", 500)
                    chunk_overlap = entry.get("chunk_overlap", 100)

                    if not model or not collections:
                        raise ValueError("The model and collections must be defined within 'Chroma'")

                    for col in collections:
                        vector_roles.append({
                            "name": col,
                            "path": f"data/{col}",
                            "model": model,
                            "chunk_size": chunk_size,
                            "chunk_overlap": chunk_overlap
                        })
    return vector_roles

def process_collection(config):
    collection_name = config['name']
    log_path = Path(f"logs/vectoritzacio/{collection_name}.log")
    log_file = open(log_path, "w", encoding="utf-8")

    def log(msg):
        print(msg)
        log_file.write(msg + "\n")

    log(f"== Starting indexing for collection: {collection_name} ==")

    model_name = config["model"]
    chunk_size = config["chunk_size"]
    chunk_overlap = config["chunk_overlap"]
    path = Path(config["path"])

    if not path.exists():
        log(f"[ERROR] Non-existent route: {path}")
        return

    download_model_if_needed(model_name)
    model = load_model(model_name)
    embedding_fn = SentenceTransformerEmbeddingFunction(model_name=model_name)
    client = chromadb.HttpClient(
        host=os.getenv("CHROMA_HOST", "localhost"),
        port=int(os.getenv("CHROMA_PORT", 8000))
    )
    collection = client.get_or_create_collection(name=collection_name, embedding_function=embedding_fn)

    files = list(path.glob("*.pdf"))
    if not files:
        log(f"[WARNING] No PDF files found in {path}")
        return

    MAX_BATCH = 5000
    indexed_total = 0
    skipped_chunks = 0

    for i, file in enumerate(tqdm(files, desc=f"Processant {collection_name}")):
        text = extract_text_from_pdf(file)
        chunks = chunk_text(text, chunk_size, chunk_overlap)

        # Filtra chunks massa llargs
        filtered = []
        ids = []
        for j, chunk in enumerate(chunks):
            if len(chunk) < 5000:
                filtered.append(chunk)
                ids.append(f"{file.stem}-chunk-{j}")
            else:
                skipped_chunks += 1
                log(f"[SKIP] Chunk too large ({len(chunk)} characters): {file.name}, chunk {j}")

        for j in range(0, len(filtered), MAX_BATCH):
            batch_docs = filtered[j:j+MAX_BATCH]
            batch_ids = ids[j:j+MAX_BATCH]
            try:
                collection.add(documents=batch_docs, ids=batch_ids)
                indexed_total += len(batch_docs)
            except Exception as e:
                log(f"[ERROR] Batch {j}-{j+MAX_BATCH} failed: {e}")

    log(f"[✓] Total indexed: {indexed_total}")
    log(f"[x] Chunks discarded by size: {skipped_chunks}")
    log(f"== Collection completed: {collection_name} ==\n")

    log_file.close()


if __name__ == "__main__":
    print("Starting document vectorization from policy-agent.yaml...")
    try:
        # Carrega variables d'entorn des de .env
        load_dotenv()
        
        log_dir = Path("logs/vectoritzacio")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        configs = load_config_from_policy_yaml()
        
        for collection_cfg in configs:
            process_collection(collection_cfg)
        print("Vectorization completed successfully.")
    except Exception as e:
        print(f"Error during vectorization: {e}")
