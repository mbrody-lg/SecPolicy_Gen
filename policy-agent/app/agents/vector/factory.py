from app.agents.vector.base import VECTOR_CLIENT_REGISTRY
from app.agents.vector.model_loader import download_model_if_needed, load_model
import importlib

def import_all_vector_modules(module_name):

    # Importa dinàmicament el mòdul client del backend
    try:
        importlib.import_module(f"app.agents.vector.{module_name}.client")
    except ImportError as e:
        raise ImportError(f"Failed to import vector backend '{module_name}': {e}")
    
    # Importa dinàmicament el mòdul client del backend
    try:
        importlib.import_module(f"app.agents.vector.{module_name}.http_client")
    except ImportError as e:
        raise ImportError(f"Could not import HttpClient from '{module_name}': {e}")

def get_vector_clients(vector_config: list):
    clients = []

    for entry in vector_config:
        if not isinstance(entry, dict):
            raise ValueError("Each entry within 'vector' must be a dictionary with a single key")

        module_name = next(iter(entry)).lower()  # ex: "chroma"
        
        import_all_vector_modules(module_name)

        backend_class = VECTOR_CLIENT_REGISTRY.get(module_name)
        if not backend_class:
            raise ValueError(f"Unsupported or unregistered backend vector: {module_name}")

        # Validació de camps requerits
        for key in ("model", "collection"):
            if key not in entry:
                raise ValueError(f"Missing '{key}' in configuration {module_name}")

        model_id = entry["model"]
        collections = entry["collection"]

        if not isinstance(collections, list):
            raise ValueError(f"'collection' must be a list for {module_name}")

        download_model_if_needed(model_id)
        model = load_model(model_id)

        vector_clients = []

        for col in collections:
            client = backend_class(model=model)
            client.load_collection(col)
            vector_clients.append(client)
            
    return vector_clients

