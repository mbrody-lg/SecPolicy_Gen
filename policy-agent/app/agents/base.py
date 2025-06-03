from abc import ABC, abstractmethod

# Diccionari global per registrar automàticament totes les subclasses
AGENT_REGISTRY = {}

class Agent(ABC):
    def __init__(self, name: str, instructions: str, model: str, tools: None, roles=None ):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools or []
        self.roles = roles or []
        self._validate_roles(self.roles)

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