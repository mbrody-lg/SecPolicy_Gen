"""Mock multi-path planner role for policy generation tests."""

class MockMultiPathPlanner:
    """Generate deterministic alternative plans from input context."""

    def generate_plans(self, context: str) -> list:
        """Return a static list of mock plan alternatives."""
        return [
            "[MOCK_PLANS]: ",
            "A: Basic protection with ISO 27001 approach",
            "B: Personal data focused approach (GDPR)",
            "C: Hybrid strategy with gradual measures",
            context
        ]
