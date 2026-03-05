"""Passive role processor that leaves prompts unchanged."""

class PassiveGoalCreator:
    """No-op prompt processor."""

    # No es modifica la proposta de prompt de l'usuari
    def execute(self, input_prompt: str) -> str:
        """Return the original input prompt without modifications."""
        return input_prompt
