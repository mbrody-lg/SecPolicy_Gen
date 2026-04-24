"""Mistral-backed validator agent implementation."""

import logging
from typing import List, Dict, Optional

import yaml
from flask import current_app

from app.agents.base import Agent
from app.agents.mistralai.client import MistralClient
from app.observability import build_log_event, log_event

logger = logging.getLogger(__name__)

class MistralAIAgent(Agent):
    """Execute validator roles using the Mistral chat backend."""

    def __init__(self, name: str, instructions: str, model: str, tools: list = None, roles: list = None):
        """Initialize Mistral backend client and prompt template configuration."""
        super().__init__(name, instructions, model, tools, roles)
        self.client = MistralClient()
        self.debug_mode = current_app.config.get("DEBUG", False)

        config_path = current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            self.prompt_template = config["agent"].get("prompt_template")

    def create(self, context_id: str = None):
        """Return synthetic creation metadata for validator sessions."""
        return {"status": "created", "context_id": context_id}

    def run(self, prompt: str, context_id: str = None, only_roles: Optional[List[Dict]] = None) -> List[Dict]:
        """Run configured roles and return parsed validation outputs."""
        selected_roles = only_roles if only_roles else self.roles

        results = []
        
        for role_config in selected_roles:
            role_key = next(iter(role_config))

            instructions = role_config.get("instructions", self.instructions)
            temperature = role_config.get("temperature", 0.7)
            max_tokens = role_config.get("max_tokens", 1000)
            log_event(
                logger,
                logging.INFO,
                event="validator.mistral.role_started",
                stage="validation",
                context_id=context_id,
                role=role_key,
                prompt_length=len(prompt),
            )

            try:
                response = self.client.chat(
                    model=self.model,
                    prompt=prompt,
                    instructions=instructions,
                    temperature=temperature,
                    max_tokens=max_tokens
                )


                content = response.choices[0].message.content.strip()
                parsed = self.parse_response_content(content)

                results.append({
                    "role": role_key,
                    "status":  parsed["status"],
                    "text": content,
                    "reason": parsed["reason"],
                    "recommendations": parsed["recommendations"]
                })
            
            except Exception as error:
                logger.warning(
                    build_log_event(
                        event="validator.mistral.role_failed",
                        stage="validation",
                        context_id=context_id,
                        role=role_key,
                        error_type=error.__class__.__name__,
                    ),
                    exc_info=error,
                )

        return results
