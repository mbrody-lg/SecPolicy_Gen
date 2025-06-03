class MockSelfReflection:
    def evaluate(self, plans: list) -> str:
        return f"[MOCK_REFLECTION] Selected plan: {plans[1]}\nReasons: Reflection simulation. Trace: {plans[0]}\n{plans[4]}"