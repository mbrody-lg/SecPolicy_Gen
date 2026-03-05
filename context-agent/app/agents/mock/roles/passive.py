"""Mock passive role that leaves input unchanged."""

class MockPassiveGoalCreator:
    """No-op passive prompt role for mocked pipelines."""

    # Keep the user prompt unchanged
    def execute(self, input_prompt: str) -> str:
        """Return the original prompt without transformation."""
        return input_prompt
