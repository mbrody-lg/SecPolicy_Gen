"""Mock passive role that leaves input unchanged."""

class MockPassiveGoalCreator:
    """No-op passive prompt role for mocked pipelines."""

    # No es modifica la proposta de prompt de l'usuari
    def execute(self, input_prompt: str) -> str:
        """Return the original prompt without transformation."""
        return input_prompt
