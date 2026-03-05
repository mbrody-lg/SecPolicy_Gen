"""Base vector client abstraction and backend registry."""

from abc import ABC, abstractmethod
from typing import List

VECTOR_CLIENT_REGISTRY = {}

class VectorClient(ABC):
    """Abstract contract implemented by vector database clients."""

    @abstractmethod
    def search(self, query: str, top_k: int = 3) -> List[str]:
        """Return top matching document chunks for a query."""
        pass

    def __init_subclass__(cls, **kwargs):
        """Auto-register concrete vector client backends by class name."""
        super().__init_subclass__(**kwargs)
        key = cls.__name__.lower().replace("vectorclient", "")
        VECTOR_CLIENT_REGISTRY[key] = cls
