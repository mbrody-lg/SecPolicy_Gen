class MockPromptResponseOptimiser:
    def execute(self, original_prompt: str, agent_response: str) -> str:
        return f"{agent_response}\n\n[Improvement: Simulated optimized response]"
