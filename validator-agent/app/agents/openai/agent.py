"""OpenAI-backed validator agent implementation."""

import logging
from typing import List, Dict, Optional

import yaml
from flask import current_app

from app.agents.base import Agent
from app.agents.openai.client import OpenAIClient
from app.observability import build_log_event, log_event

logger = logging.getLogger(__name__)

class OpenAIAgent(Agent):
    """Execute validator roles using OpenAI chat completions."""

    def __init__(self, name: str, instructions: str, model: str, tools: list = None, roles: list = None):
        """Initialize OpenAI backend and load optional prompt template."""
        super().__init__(name, instructions, model, tools, roles)
        self.client = OpenAIClient()
        self.debug_mode = current_app.config.get("DEBUG", False)

        config_path = current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            self.prompt_template = config["agent"].get("prompt_template")

    def create(self, context_id: str = None):
        """Create logical session metadata for validator operations."""
        return {"id": context_id or "openai-policy-session"}

    def run(self, prompt: str, context_id: str = None, only_roles: Optional[List[Dict]] = None) -> List[Dict]:
        """Run configured roles and return parsed validation outputs."""
        selected_roles = only_roles if only_roles else self.roles

        results = []
        for role_config in selected_roles:
            role_key = next(iter(role_config))

            instructions = role_config.get("instructions", self.instructions)
            temperature = role_config.get("temperature", 0.7)
            max_tokens = role_config.get("max_tokens", 1000)

            full_prompt = self._render_prompt(instructions, prompt)
            log_event(
                logger,
                logging.INFO,
                event="validator.openai.role_started",
                stage="validation",
                context_id=context_id,
                role=role_key,
                prompt_length=len(full_prompt),
            )

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": full_prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = response.choices[0].message.content.strip()
                parsed = self.parse_response_content(content)
                results.append({
                    "role": role_key,
                    "status": parsed["status"],  # Adapt if output schema changes
                    "text": content,
                    "reason": parsed["reason"],
                    "recommendations": parsed["recommendations"]  # Can be further extracted if embedded in text
                })

            except Exception as error:
                logger.warning(
                    build_log_event(
                        event="validator.openai.role_failed",
                        stage="validation",
                        context_id=context_id,
                        role=role_key,
                        error_type=error.__class__.__name__,
                    ),
                    exc_info=error,
                )
                continue
                
        return results
