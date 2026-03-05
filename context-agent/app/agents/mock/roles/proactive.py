"""Mock proactive role used for non-LLM local testing."""

class MockProactiveGoalCreator:
    """Append a deterministic proactive marker to the prompt."""

    def execute(self, input_prompt: str) -> str:
        """Return the input prompt with mock proactive enhancement text."""
        return f"{input_prompt}\n\n[Add: Mock Proactive Enhancement]"
