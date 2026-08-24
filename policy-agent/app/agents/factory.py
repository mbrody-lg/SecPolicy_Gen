"""Factory helpers to load policy-agent configuration and backends."""

import importlib

import yaml

from app.agents.base import AGENT_REGISTRY, get_role_name

MAX_PROPOSALS = 10


def _required_string(config: dict, key: str, location: str = "Configuration") -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} field '{key}' must be a non-empty string.")
    return value.strip()


def validate_agent_config(config: dict) -> dict:
    """Validate the policy-agent YAML contract before provider execution."""
    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a mapping.")

    for key in ("type", "name", "instructions", "model"):
        _required_string(config, key)

    roles = config.get("roles")
    if not isinstance(roles, list) or not roles:
        raise ValueError("Configuration field 'roles' must be a non-empty list.")

    configured_model = config["model"].strip()
    configured_roles = set()
    for index, role in enumerate(roles):
        location = f"Role {index + 1}"
        if not isinstance(role, dict) or not role:
            raise ValueError(f"{location} must be a non-empty mapping.")

        role_name = get_role_name(role)
        if role_name in configured_roles:
            raise ValueError(f"Role '{role_name}' must only be configured once.")
        configured_roles.add(role_name)
        location = f"Role '{role_name}'"
        _required_string(role, "instructions", location)

        role_model = role.get("model")
        if role_model is not None:
            role_model = _required_string(role, "model", location)
            if role_model != configured_model:
                raise ValueError(
                    f"{location} model must match the top-level configuration model."
                )

        temperature = role.get("temperature", 0.7)
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0 <= temperature <= 2
        ):
            raise ValueError(f"{location} temperature must be between 0 and 2.")

        max_tokens = role.get("max_tokens", 1000)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError(f"{location} max_tokens must be a positive integer.")

        if "proposals" in role:
            proposals = role["proposals"]
            if (
                isinstance(proposals, bool)
                or not isinstance(proposals, int)
                or not 1 <= proposals <= MAX_PROPOSALS
            ):
                raise ValueError(
                    f"{location} proposals must be an integer between 1 and {MAX_PROPOSALS}."
                )

    return config

def load_agent_config(config_path: str) -> dict:
    """Load policy agent settings from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return validate_agent_config(yaml.safe_load(f))

def create_agent_from_config(config: dict):
    """Instantiate a policy-agent backend from parsed configuration."""
    config = validate_agent_config(config)
    agent_type = config["type"].strip().lower()  # example: "openai", "claude", "mock"
    module_path = f"app.agents.{agent_type}.agent"

    try:
        # Dynamically import backend module (example: app.agents.openai.agent)
        importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        raise ImportError(
            f"Agent backend '{agent_type}' not supported. Error: {error}"
        ) from error

    # Expected registry identifier
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
