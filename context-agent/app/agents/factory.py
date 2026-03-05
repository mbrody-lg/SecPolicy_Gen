"""Factory helpers to load and instantiate context-agent backends."""

import importlib
import yaml
from app.agents.base import AGENT_REGISTRY

def load_agent_config(config_path: str) -> dict:
    """Load agent configuration from a YAML file path."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def create_agent_from_config(config_path: str):
    """Create an agent instance from YAML configuration."""
    config = load_agent_config(config_path)
    agent_type = config.get("type").lower()  # example: "openai", "claude", "mock"
    module_path = f"app.agents.{agent_type}.agent"

    try:
        # Dynamically import the backend module (example: app.agents.openai.agent)
        importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        raise ImportError(
            f"Agent backend '{agent_type}' is not supported. Error: {error}"
        ) from error

    # Expected registry identifier
    registry_key = f"{agent_type}"
    agent_class = AGENT_REGISTRY.get(registry_key)
    
    if not agent_class:
        raise ValueError(f"No agent has been registered with type '{agent_type}'")

    return agent_class(
        name=config["name"],
        instructions=config["instructions"],
        model=config["model"],
        tools=config.get("tools", [])
    )
