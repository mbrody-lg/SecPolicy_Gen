from abc import ABC, abstractmethod
import re

# Diccionari global per registrar automàticament totes les subclasses
AGENT_REGISTRY = {}

class Agent(ABC):
    def __init__(self, name: str, instructions: str, model: str, tools: list = []):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools

    # Registre automàtic de subclasses
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # El nom del tipus (per exemple "mock" ve de "MockAgent")
        registry_key = cls.__name__.lower().replace("agent", "")
        AGENT_REGISTRY[registry_key] = cls

    @abstractmethod
    def create(self, context_id: str = None):
        pass

    @abstractmethod
    def run(self, prompt: str, context_id: str = None) -> str:
        pass
