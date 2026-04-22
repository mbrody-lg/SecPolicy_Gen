"""Helpers to cache, download, and load sentence-transformer models securely."""

import os
from pathlib import Path
from typing import Iterable

from huggingface_hub import snapshot_download
from huggingface_hub.utils import RepositoryNotFoundError, RevisionNotFoundError

SAFE_HUB_FILE_PATTERNS = [
    "*.json",
    "*.md",
    "*.model",
    "*.py",
    "*.safetensors",
    "*.txt",
    "modules.json",
    "special_tokens_map.json",
    "tokenizer*",
    "vocab*",
]
UNSAFE_MODEL_FILE_PATTERNS = [
    "*.bin",
    "*.ckpt",
    "*.h5",
    "*.msgpack",
    "*.pickle",
    "*.pkl",
    "*.pt",
    "*.pth",
    "flax_model.msgpack",
    "pytorch_model.bin",
]


def _allow_model_download() -> bool:
    value = os.getenv("POLICY_AGENT_ALLOW_MODEL_DOWNLOAD", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_model_cache_path(model_id: str) -> str:
    """Return local Hugging Face cache path for a model id."""
    return os.path.expanduser(f"~/.cache/huggingface/hub/models--{model_id.replace('/', '--')}")


def is_model_cached(model_id: str) -> bool:
    """Check whether a model already exists in the local cache."""
    if not model_id:
        raise ValueError("'model' not specified in YAML.")
    return os.path.exists(get_model_cache_path(model_id))


def has_safetensors_weights(model_id: str) -> bool:
    """Return whether the cached model exposes safetensors weights."""
    cache_path = Path(get_model_cache_path(model_id))
    return cache_path.exists() and any(cache_path.rglob("*.safetensors"))


def download_model_if_needed(model_id: str, revision: str | None = None):
    """Download a model snapshot when explicitly allowed and not available locally."""
    if not model_id:
        raise ValueError("'model' not specified. It must be indicated explicitly.")

    if not is_model_cached(model_id):
        if not _allow_model_download():
            raise RuntimeError(
                "The model is not cached locally. Preload it with scripts/index_pdfs_to_chroma.py "
                "or set POLICY_AGENT_ALLOW_MODEL_DOWNLOAD=1 for an explicit one-time download."
            )
        print(f"Model '{model_id}' not found locally. Downloading...")
        try:
            snapshot_download(
                repo_id=model_id,
                revision=revision,
                allow_patterns=SAFE_HUB_FILE_PATTERNS,
                ignore_patterns=UNSAFE_MODEL_FILE_PATTERNS,
            )
            print("Model downloaded successfully.")
        except (RepositoryNotFoundError, RevisionNotFoundError) as error:
            raise RuntimeError(
                f"Could not download model. '{model_id}': {error}"
            ) from error

    if not has_safetensors_weights(model_id):
        raise RuntimeError(
            f"The model '{model_id}' does not expose safetensors weights in local cache."
        )


def load_model(model_id: str, revision: str | None = None):
    """Load a sentence-transformer model from local cache with secure defaults."""
    from sentence_transformers import SentenceTransformer

    if not model_id:
        raise ValueError("'model' not specified. Unable to load.")
    if not is_model_cached(model_id):
        raise RuntimeError(f"The model '{model_id}' is not available locally. You need to download it first.")
    if not has_safetensors_weights(model_id):
        raise RuntimeError(
            f"The model '{model_id}' is missing safetensors weights. Refusing to load unsafe serialization."
        )

    return SentenceTransformer(
        model_id,
        revision=revision,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )


class LocalSentenceTransformerEmbeddingFunction:
    """Chroma-compatible embedding function backed by a preloaded local model."""

    def __init__(self, model, *, normalize_embeddings: bool = True):
        self.model = model
        self.normalize_embeddings = normalize_embeddings

    def __call__(self, input_texts: Iterable[str]):
        embeddings = self.model.encode(
            list(input_texts),
            normalize_embeddings=self.normalize_embeddings,
        )
        return embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings
