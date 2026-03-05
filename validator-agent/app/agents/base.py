"""Base abstractions and shared parsing helpers for validator agents."""

from abc import ABC, abstractmethod
from typing import Dict
import re

# Global dictionary used to auto-register all subclasses
AGENT_REGISTRY = {}

class Agent(ABC):
    """Abstract base contract for validator-agent backends."""

    def __init__(self, name: str, instructions: str, model: str, tools: None, roles=None):
        """Initialize common agent state and validate configured roles."""
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools or []
        self.roles = roles or []
        self._validate_roles(self.roles)
        self.roles_by_key = {list(r.keys())[0]: r[list(r.keys())[0]] for r in self.roles}


    def __init_subclass__(cls, **kwargs):
        """Auto-register concrete subclasses in the global agent registry."""
        super().__init_subclass__(**kwargs)
        registry_key = cls.__name__.lower().replace("agent", "")
        AGENT_REGISTRY[registry_key] = cls

    @abstractmethod
    def create(self, context_id: str = None):
        """Create remote/session resources required by the concrete backend."""
        pass

    @abstractmethod
    def run(self, prompt: str, context_id: str = None) -> str:
        """Execute the concrete validation flow and return backend output."""
        pass

    def _validate_roles(self, roles: list):
        """Validate role structure and required role configuration fields."""
        if not roles or not isinstance(roles, list):
            raise ValueError("The YAML must contain a list of 'roles'.")

        for role in roles:
            role_key = next(iter(role.keys()), None)
            if role_key is None:
                raise ValueError("One of the 'roles' does not have an identifying key (ex: RAG, MPG, etc.)")
            
            if "instructions" not in role:
                raise ValueError(f"Role '{role_key}' does not have the required key 'instructions'.")

            temperature = role.get("temperature", 0.7)
            max_tokens = role.get("max_tokens", 1000)

            if not isinstance(temperature, (float, int)):
                raise ValueError(f"Role '{role_key}' has an invalid 'temperature': {temperature}")

            if not isinstance(max_tokens, int):
                raise ValueError(f"Role '{role_key}' has an invalid 'max_tokens': {max_tokens}")

    def parse_response_content(self, content: str) -> Dict:
        """
        Attempt to extract status, reason, and recommendations from generated content.
        Return a dictionary with expected output fields.
        """
        result = {
            "status": "accepted",  # default
            "reason": "",
            "recommendations": []
        }

        # Status
        match = re.search(r"\*\*?STATUS:?[\*\s]*([a-zA-Z]+)", content, re.IGNORECASE)
        if match:
            result["status"] = match.group(1).lower()

        # Reason
        match = re.search(r"\*\*?REASON:?[\*\s]*(.+?)(?=\n\*\*?RECOMMENDATIONS|\Z)", content, re.IGNORECASE | re.DOTALL)
        if match:
            reason_text = match.group(1).strip()
            result["reason"] = reason_text

        # Recommendations section: capture until end of content
        match = re.search(r"\*\*RECOMMENDATIONS:?\*\*\s*(.+)$", content, re.IGNORECASE | re.DOTALL)
        if match:
            recommendations_block = match.group(1).strip()
            lines = recommendations_block.splitlines()
            recs = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^([-•]|\d+\.)\s+", line):
                    rec = re.sub(r"^([-•]|\d+\.)\s*", "", line).strip()
                    recs.append(rec)
                else:
                    if recs:
                        recs[-1] += " " + line
                    else:
                        recs.append(line)

            result["recommendations"] = recs

        return result
    
    def _render_prompt(self, instructions: str, prompt: str) -> str:
        """Render the final prompt, honoring optional prompt template configuration."""
        return self.prompt_template.format(
            instructions=instructions.strip(),
            prompt=prompt.strip()
        ) if self.prompt_template else f"{instructions.strip()}\n\n{prompt.strip()}"
