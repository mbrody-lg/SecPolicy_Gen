"""Mock response optimizer used in tests and local runs."""

class MockPromptResponseOptimiser:
    """Return a deterministic optimized response marker."""

    def execute(self, _original_prompt: str, agent_response: str) -> str:
        """Append mock optimization metadata to an agent response."""
        return f"{agent_response}\n\n[Improvement: Simulated optimized response]"
