from abc import ABC, abstractmethod
from typing import List

VECTOR_CLIENT_REGISTRY = {}

class VectorClient(ABC):
    @abstractmethod
    def search(self, query: str, top_k: int = 3) -> List[str]:
        pass

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        key = cls.__name__.lower().replace("vectorclient", "")
        VECTOR_CLIENT_REGISTRY[key] = cls