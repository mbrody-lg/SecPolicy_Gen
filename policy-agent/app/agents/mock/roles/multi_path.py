class MockMultiPathPlanner:
    def generate_plans(self, context: str) -> list:
        return [
            "[MOCK_PLANS]: ",
            "A: Basic protection with ISO 27001 approach",
            "B: Personal data focused approach (GDPR)",
            "C: Hybrid strategy with gradual measures",
            context
        ]