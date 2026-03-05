"""Passive role processor that leaves prompts unchanged."""

class PassiveGoalCreator:
    """No-op prompt processor."""

    # Keep the user prompt unchanged
    def execute(self, input_prompt: str) -> str:
        """Return the original input prompt without modifications."""
        return input_prompt
