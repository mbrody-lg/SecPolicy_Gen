"""Mock self-reflection role implementation."""

class MockSelfReflection:
    """Select and justify a mock plan deterministically."""

    def evaluate(self, plans: list) -> str:
        """Return a synthetic reflection result over generated plans."""
        return f"[MOCK_REFLECTION] Selected plan: {plans[1]}\nReasons: Reflection simulation. Trace: {plans[0]}\n{plans[4]}"
