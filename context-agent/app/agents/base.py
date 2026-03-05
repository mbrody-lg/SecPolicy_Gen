"""Base abstractions and registry for context-agent implementations."""

from abc import ABC, abstractmethod

# Diccionari global per registrar automàticament totes les subclasses
AGENT_REGISTRY = {}

class Agent(ABC):
    """Abstract base class for context-generation agent backends."""

    def __init__(self, name: str, instructions: str, model: str, tools=None):
        """Initialize common agent metadata and configured tool list."""
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools or []

    # Registre automàtic de subclasses
    def __init_subclass__(cls, **kwargs):
        """Auto-register each concrete subclass by backend key."""
        super().__init_subclass__(**kwargs)
        # El nom del tipus (per exemple "mock" ve de "MockAgent")
        registry_key = cls.__name__.lower().replace("agent", "")
        AGENT_REGISTRY[registry_key] = cls

    @abstractmethod
    def create(self, context_id: str = None):
        """Create or restore backend runtime state for an optional context."""
        pass

    @abstractmethod
    def run(self, prompt: str, context_id: str = None) -> str:
        """Execute prompt generation for the provided context."""
        pass
