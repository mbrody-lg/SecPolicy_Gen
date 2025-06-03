import os
from sentence_transformers import SentenceTransformer
from huggingface_hub import snapshot_download
from huggingface_hub.utils import RepositoryNotFoundError, RevisionNotFoundError

def get_model_cache_path(model_id: str) -> str:
    return os.path.expanduser(f"~/.cache/huggingface/hub/models--{model_id.replace('/', '--')}")

def is_model_cached(model_id: str) -> bool:
    if not model_id:
        raise ValueError("'model' not specified in YAML.")
    return os.path.exists(get_model_cache_path(model_id))

def download_model_if_needed(model_id: str):
    if not model_id:
        raise ValueError("'model' not specified. It must be indicated explicitly.")
    
    if not is_model_cached(model_id):
        print(f"Model '{model_id}' not found locally. Downloading...")
        try:
            snapshot_download(repo_id=model_id)
            print("Model downloaded successfully.")
        except (RepositoryNotFoundError, RevisionNotFoundError) as e:
            raise RuntimeError(f"Could not download model. '{model_id}': {str(e)}")

def load_model(model_id: str) -> SentenceTransformer:
    if not model_id:
        raise ValueError("'model' not specified. Unable to load.")
    
    if not is_model_cached(model_id):
        raise RuntimeError(f"The model '{model_id}' is not available locally. You need to download it first.")
    
    return SentenceTransformer(model_id)
