import importlib
import yaml
from app.agents.base import AGENT_REGISTRY

def load_agent_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def create_agent_from_config(config_path: str):
    config = load_agent_config(config_path)
    agent_type = config.get("type").lower()  # ex: "openai", "claude", "mock"
    module_path = f"app.agents.{agent_type}.agent"

    try:
        # Dinàmicament importa el mòdul (ex: app.agents.openai.agent)
        importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(f"Agent backend '{agent_type}' no suportat. Error: {e}")

    # Identificador esperat al registre
    registry_key = f"{agent_type}"
    agent_class = AGENT_REGISTRY.get(registry_key)
    
    if not agent_class:
        raise ValueError(f"No s'ha registrat cap agent amb el tipus '{agent_type}'")

    return agent_class(
        name=config["name"],
        instructions=config["instructions"],
        model=config["model"],
        tools=config.get("tools", [])
    )
