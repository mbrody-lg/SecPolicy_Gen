"""Factory helpers to load policy-agent configuration and backends."""

import importlib
import yaml
from app.agents.base import AGENT_REGISTRY

def load_agent_config(config_path: str) -> dict:
    """Load policy agent settings from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def create_agent_from_config(config: str):
    """Instantiate a policy-agent backend from parsed configuration."""
    agent_type = config.get("type").lower()  # ex: "openai", "claude", "mock"
    module_path = f"app.agents.{agent_type}.agent"

    try:
        # Dinàmicament importa el mòdul (ex: app.agents.openai.agent)
        importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        raise ImportError(
            f"Agent backend '{agent_type}' not supported. Error: {error}"
        ) from error

    # Identificador esperat al registre
    registry_key = f"{agent_type}"
    agent_class = AGENT_REGISTRY.get(registry_key)
    
    if not agent_class:
        raise ValueError(f"No agent has been registered with the type '{agent_type}'")

    return agent_class(
        name=config["name"],
        instructions=config["instructions"],
        model=config["model"],
        roles=config.get("roles", []),
        tools=config.get("tools", [])
    )
