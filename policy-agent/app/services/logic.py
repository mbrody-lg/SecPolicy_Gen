"""Service helpers for policy-agent configuration and execution flow."""

import os
from datetime import datetime, timezone

import yaml
from flask import current_app

from app import mongo
from app.agents.factory import create_agent_from_config


def load_policy_config() -> dict:
    """Load policy-agent YAML configuration from configured path."""
    config_path = os.path.join(current_app.config["CONFIG_PATH"])

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def run_with_agent(refined_prompt: str, context_id: str, model_version: str) -> str:
    """Run full policy-agent role pipeline for initial policy generation."""
    config = load_policy_config()
    
    mongo.db.policy_configs.update_one(
        {"model_version": model_version},
        {
            "$set": {
                "model_version": model_version,
                "yaml_content": config,
                "updated_at": datetime.now(timezone.utc)
            }
        },
        upsert=True
    )
    
    # Create agent from YAML configuration
    agent = create_agent_from_config(config)

    # Execute full pipeline with roles defined in YAML
    if current_app.config["DEBUG"]:
        print(f"[INFO] Running policy-agent ({model_version}) for context_id={context_id}")
    return agent.run(prompt=refined_prompt, context_id=context_id)

def update_with_agent(prompt: str, context_id: str = None, model_version: str = None) -> str:
    """Run only update role pipeline to revise an existing policy text."""
    config = load_policy_config()
    
    # Create agent from YAML configuration
    agent = create_agent_from_config(config)
    
    # Execute only the last role (IMQ)
    last_role = [agent.roles[-1]]
    agent.roles = last_role

    if current_app.config["DEBUG"]:
        print(f"[INFO] Running policy-agent ({model_version}) for context_id={context_id} role={last_role} & PROMPT:{prompt}")
    return agent.run(prompt, context_id)
