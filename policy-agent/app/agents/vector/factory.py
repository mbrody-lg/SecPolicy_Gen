"""Factory utilities to import and construct vector backend clients."""

import importlib

from app.agents.vector.base import VECTOR_CLIENT_REGISTRY
from app.agents.vector.model_loader import download_model_if_needed, load_model


def import_all_vector_modules(module_name):
    """Import backend client modules required for a vector provider."""

    # Dynamically import backend client module
    try:
        importlib.import_module(f"app.agents.vector.{module_name}.client")
    except ImportError as error:
        raise ImportError(
            f"Failed to import vector backend '{module_name}': {error}"
        ) from error
    
    # Dynamically import backend HTTP client module
    try:
        importlib.import_module(f"app.agents.vector.{module_name}.http_client")
    except ImportError as error:
        raise ImportError(
            f"Could not import HttpClient from '{module_name}': {error}"
        ) from error

def get_vector_clients(vector_config: list):
    """Create vector backend clients from YAML role configuration."""
    for entry in vector_config:
        if not isinstance(entry, dict):
            raise ValueError("Each entry within 'vector' must be a dictionary with a single key")

        module_name = next(iter(entry)).lower()  # ex: "chroma"
        
        import_all_vector_modules(module_name)

        backend_class = VECTOR_CLIENT_REGISTRY.get(module_name)
        if not backend_class:
            raise ValueError(f"Unsupported or unregistered backend vector: {module_name}")

        # Required field validation
        for key in ("model", "collection"):
            if key not in entry:
                raise ValueError(f"Missing '{key}' in configuration {module_name}")

        model_id = entry["model"]
        revision = entry.get("revision")
        collections = entry["collection"]

        if not isinstance(collections, list):
            raise ValueError(f"'collection' must be a list for {module_name}")

        download_model_if_needed(model_id, revision=revision)
        model = load_model(model_id, revision=revision)

        vector_clients = []

        for col in collections:
            client = backend_class(model=model)
            client.load_collection(col)
            vector_clients.append(client)
            
    return vector_clients
