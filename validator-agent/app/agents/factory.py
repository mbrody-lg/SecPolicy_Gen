"""Factory helpers to load validator-agent backend implementations."""

import importlib
from pathlib import Path

import yaml
from flask import current_app

from app.agents.base import AGENT_REGISTRY

def load_agent_config(config_path: str = None) -> dict:
    """Load validator-agent configuration from disk."""
    path = config_path or current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def create_agent_from_config(config: dict):
    """Instantiate and return the configured backend agent implementation."""
    agent_type = config.get("type", "").lower()
    module_path = f"app.agents.{agent_type}.agent"
    
    try:
        importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        raise ImportError(
            f"Agent backend '{agent_type}' not supported. Error: {error}"
        ) from error

    agent_class = AGENT_REGISTRY.get(agent_type)
    if not agent_class:
        raise ValueError(
            f"No agent has been registered with the type '{agent_type}'. "
            f"Available agents: {list(AGENT_REGISTRY.keys())}"
        )

    return agent_class(
        name=config["name"],
        instructions=config["instructions"],
        model=config["model"],
        roles=config.get("roles", []),
        tools=config.get("tools", [])
    )
