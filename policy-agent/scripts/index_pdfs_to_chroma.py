"""Index policy-agent RAG source documents into Chroma."""

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from pypdf import PdfReader
from tqdm import tqdm

POLICY_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(POLICY_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(POLICY_AGENT_ROOT))

from app.agents.vector.chroma.config import get_chroma_host, get_chroma_port
from app.rag.sources import load_rag_source_manifest

MAX_BATCH = 5000
MAX_CHUNK_CHARACTERS = 5000
TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"", "0", "false", "no", "off"}


def extract_text_from_pdf(path):
    """Extract text from a PDF file."""
    reader = PdfReader(path)
    return "".join(page.extract_text() or "" for page in reader.pages)


def chunk_text(text, size, overlap):
    """Split text into overlapping character chunks."""
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


def load_configs_from_rag_sources(path=None, collection_filter=None):
    """Load indexable source configs from the RAG source manifest."""
    manifest_path = path or os.getenv("RAG_SOURCES_PATH", "app/config/rag_sources.yaml")
    manifest = load_rag_source_manifest(manifest_path)
    defaults = manifest.get("embedding_defaults", {})
    file_types = defaults.get("file_types", ["pdf"])

    configs = []
    for source in manifest["sources"]:
        collection_name = source["collection"]
        if collection_filter and collection_name != collection_filter:
            continue

        configs.append(
            {
                "source_id": source["id"],
                "name": collection_name,
                "path": source["path"],
                "family": source["family"],
                "include": source.get("include"),
                "metadata": source["metadata"],
                "model": defaults.get("model"),
                "revision": defaults.get("revision"),
                "chunk_size": defaults.get("chunk_size", 500),
                "chunk_overlap": defaults.get("chunk_overlap", 100),
                "file_types": file_types,
            }
        )

    return configs


def discover_files(config):
    """Return source files selected by one manifest entry."""
    source_path = Path(config["path"])
    if not source_path.exists():
        return []

    include_patterns = config.get("include")
    if include_patterns:
        files = []
        for pattern in include_patterns:
            files.extend(source_path.glob(pattern))
        return sorted({path for path in files if path.is_file()})

    files = []
    for file_type in config.get("file_types", ["pdf"]):
        files.extend(source_path.glob(f"*.{file_type}"))
    return sorted({path for path in files if path.is_file()})


def validate_source_configs(configs, *, check_chroma=False):
    """Validate selected RAG sources without loading models or mutating Chroma."""
    collections = []
    totals = {"sources": 0, "files": 0, "collections": 0}

    for config in configs:
        totals["sources"] += 1
        collection_name = config["name"]
        if collection_name not in collections:
            collections.append(collection_name)

        source_path = Path(config["path"])
        if not source_path.exists():
            raise FileNotFoundError(
                f"RAG source '{config['source_id']}' path does not exist: {source_path}"
            )
        if not source_path.is_dir():
            raise NotADirectoryError(
                f"RAG source '{config['source_id']}' path must be a directory: {source_path}"
            )

        files = discover_files(config)
        totals["files"] += len(files)
        print(
            "[VALIDATE] "
            f"{config['source_id']} -> {collection_name}: path={source_path} files={len(files)}"
        )

    totals["collections"] = len(collections)
    print(f"[VALIDATE] Collections selected: {', '.join(collections)}")

    if check_chroma:
        _validate_chroma_reachable()
    else:
        print("[VALIDATE] Chroma reachability: skipped")

    return totals


def _validate_chroma_reachable():
    """Run a lightweight Chroma heartbeat without touching collections or models."""
    host = get_chroma_host(default="localhost")
    port = get_chroma_port(default="8000")
    chromadb = _get_chromadb()
    client = chromadb.HttpClient(host=host, port=port)
    client.heartbeat()
    print(f"[VALIDATE] Chroma reachability: ok ({host}:{port})")


def _get_chromadb():
    """Import Chroma lazily so validate-only can run without vector dependencies."""
    import chromadb

    return chromadb


def build_chunk_id(config, file_path, chunk_index):
    """Build a stable chunk id scoped by source and collection."""
    return f"{config['name']}:{config['source_id']}:{file_path.stem}:chunk-{chunk_index}"


def build_chunk_metadata(config, file_path, chunk_index):
    """Build Chroma-safe metadata for one chunk."""
    metadata = {
        "source_id": config["source_id"],
        "collection": config["name"],
        "collection_family": config["family"],
        "source_doc": file_path.name,
        "source_stem": file_path.stem,
        "chunk_index": chunk_index,
    }
    for key, value in config["metadata"].items():
        if isinstance(value, list):
            metadata[key] = ",".join(value)
        else:
            metadata[key] = value
    return metadata


def _with_model_download_enabled(callback):
    original_allow_download = os.getenv("POLICY_AGENT_ALLOW_MODEL_DOWNLOAD")
    os.environ["POLICY_AGENT_ALLOW_MODEL_DOWNLOAD"] = "1"
    try:
        return callback()
    finally:
        if original_allow_download is None:
            os.environ.pop("POLICY_AGENT_ALLOW_MODEL_DOWNLOAD", None)
        else:
            os.environ["POLICY_AGENT_ALLOW_MODEL_DOWNLOAD"] = original_allow_download


def _get_chroma_collection(config, reindex=False):
    from app.agents.vector.model_loader import (
        LocalSentenceTransformerEmbeddingFunction,
        download_model_if_needed,
        load_model,
    )

    model_name = config["model"]
    revision = config.get("revision")
    if not model_name:
        raise ValueError("RAG source manifest embedding_defaults.model is required.")

    _with_model_download_enabled(lambda: download_model_if_needed(model_name, revision=revision))
    model = load_model(model_name, revision=revision)
    embedding_fn = LocalSentenceTransformerEmbeddingFunction(model)
    chromadb = _get_chromadb()
    client = chromadb.HttpClient(
        host=get_chroma_host(default="localhost"),
        port=get_chroma_port(default="8000"),
    )
    if reindex:
        try:
            client.delete_collection(config["name"])
        except Exception:
            pass
    return client.get_or_create_collection(name=config["name"], embedding_function=embedding_fn)


def process_source(config, *, dry_run=False, reindex=False):
    """Index one manifest source config into its target collection."""
    collection_name = config["name"]
    log_path = Path(f"logs/vectorization/{collection_name}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_file:

        def log(msg):
            print(msg)
            log_file.write(msg + "\n")

        log(f"== Starting indexing for source: {config['source_id']} -> {collection_name} ==")

        files = discover_files(config)
        if not files:
            log(f"[WARNING] No source files found in {config['path']}")
            return {"indexed": 0, "skipped": 0, "files": 0}

        if dry_run:
            log(f"[DRY-RUN] Files selected: {len(files)}")
            return {"indexed": 0, "skipped": 0, "files": len(files)}

        collection = _get_chroma_collection(config, reindex=reindex)
        indexed_total = 0
        skipped_chunks = 0

        for file_path in tqdm(files, desc=f"Processing {config['source_id']}"):
            text = extract_text_from_pdf(file_path)
            chunks = chunk_text(text, config["chunk_size"], config["chunk_overlap"])

            filtered_docs = []
            ids = []
            metadatas = []
            for chunk_index, chunk in enumerate(chunks):
                if len(chunk) < MAX_CHUNK_CHARACTERS:
                    filtered_docs.append(chunk)
                    ids.append(build_chunk_id(config, file_path, chunk_index))
                    metadatas.append(build_chunk_metadata(config, file_path, chunk_index))
                else:
                    skipped_chunks += 1
                    log(f"[SKIP] Chunk too large ({len(chunk)} characters): {file_path.name}, chunk {chunk_index}")

            for batch_start in range(0, len(filtered_docs), MAX_BATCH):
                batch_docs = filtered_docs[batch_start:batch_start + MAX_BATCH]
                batch_ids = ids[batch_start:batch_start + MAX_BATCH]
                batch_metadatas = metadatas[batch_start:batch_start + MAX_BATCH]
                try:
                    collection.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metadatas)
                    indexed_total += len(batch_docs)
                except Exception as error:
                    log(f"[ERROR] Batch {batch_start}-{batch_start + MAX_BATCH} failed: {error}")

        log(f"[OK] Total indexed: {indexed_total}")
        log(f"[x] Chunks discarded by size: {skipped_chunks}")
        log(f"== Source completed: {config['source_id']} ==\n")

    return {"indexed": indexed_total, "skipped": skipped_chunks, "files": len(files)}


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Index RAG source documents into Chroma.")
    parser.add_argument("--manifest", default=os.getenv("RAG_SOURCES_PATH", "app/config/rag_sources.yaml"))
    parser.add_argument("--collection", help="Only process sources targeting this collection.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and list source files without indexing.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate manifest, source paths, and collection names without indexing.",
    )
    parser.add_argument(
        "--validate-chroma",
        action="store_true",
        help="With --validate-only, also run a lightweight Chroma heartbeat.",
    )
    parser.add_argument("--reindex", action="store_true", help="Delete target collection before indexing each source.")
    return parser.parse_args()


def main():
    """Run document vectorization from the RAG source manifest."""
    load_dotenv()
    args = parse_args()
    configs = load_configs_from_rag_sources(args.manifest, collection_filter=args.collection)

    if not configs:
        raise ValueError("No RAG source configs selected.")

    print(f"Loaded {len(configs)} RAG source config(s).")
    if args.validate_only:
        check_chroma = args.validate_chroma or _env_flag_enabled("RAG_VALIDATE_CHROMA")
        totals = validate_source_configs(configs, check_chroma=check_chroma)
        print(
            "RAG validation completed successfully. "
            f"sources={totals['sources']} collections={totals['collections']} files={totals['files']}"
        )
        return

    dry_run = args.dry_run or args.validate_only
    totals = {"indexed": 0, "skipped": 0, "files": 0}
    reindexed_collections = set()
    for config in configs:
        should_reindex = args.reindex and config["name"] not in reindexed_collections
        result = process_source(config, dry_run=dry_run, reindex=should_reindex)
        reindexed_collections.add(config["name"])
        for key in totals:
            totals[key] += result[key]

    print(
        "Vectorization completed successfully. "
        f"files={totals['files']} indexed={totals['indexed']} skipped={totals['skipped']}"
    )


def _env_flag_enabled(name):
    """Parse an explicit environment flag without accepting ambiguous values."""
    value = os.getenv(name, "").strip().lower()
    if value in TRUTHY_VALUES:
        return True
    if value in FALSY_VALUES:
        return False
    allowed_values = sorted((TRUTHY_VALUES | FALSY_VALUES) - {""})
    raise ValueError(f"{name} must be one of: {', '.join(allowed_values)}.")


if __name__ == "__main__":
    main()
