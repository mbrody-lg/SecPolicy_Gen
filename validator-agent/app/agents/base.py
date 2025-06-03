from abc import ABC, abstractmethod
from typing import Dict
import re

# Diccionari global per registrar automàticament totes les subclasses
AGENT_REGISTRY = {}

class Agent(ABC):
    def __init__(self, name: str, instructions: str, model: str, tools: None, roles=None):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools or []
        self.roles = roles or []
        self._validate_roles(self.roles)
        self.roles_by_key = {list(r.keys())[0]: r[list(r.keys())[0]] for r in self.roles}


    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        registry_key = cls.__name__.lower().replace("agent", "")
        AGENT_REGISTRY[registry_key] = cls

    @abstractmethod
    def create(self, context_id: str = None):
        pass

    @abstractmethod
    def run(self, prompt: str, context_id: str = None) -> str:
        pass

    def _validate_roles(self, roles: list):
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
            Intenta extreure status, raó i recomanacions del contingut generat.
            Retorna un diccionari amb els camps esperats.
            """
            result = {
                "status": "accepted",  # per defecte
                "reason": "",
                "recommendations": []
            }

            # STATUS
            match = re.search(r"\*\*?STATUS:?[\*\s]*([a-zA-Z]+)", content, re.IGNORECASE)
            if match:
                result["status"] = match.group(1).lower()

            # REASON
            match = re.search(r"\*\*?REASON:?[\*\s]*(.+?)(?=\n\*\*?RECOMMENDATIONS|\Z)", content, re.IGNORECASE | re.DOTALL)
            if match:
                reason_text = match.group(1).strip()
                result["reason"] = reason_text

            # RECOMMENDATIONS agafa fins al final del content
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
        return self.prompt_template.format(
            instructions=instructions.strip(),
            prompt=prompt.strip()
        ) if self.prompt_template else f"{instructions.strip()}\n\n{prompt.strip()}"