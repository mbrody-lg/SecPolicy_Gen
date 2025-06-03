class MockProactiveGoalCreator:
    def execute(self, input_prompt: str) -> str:
        return f"{input_prompt}\n\n[Add: Mock Proactive Enhancement]"
