"""Mock incremental-query role implementation."""

class MockIncrementalQuery:
    """Apply a deterministic refinement marker to a mock plan."""

    def refine(self, plan: str) -> str:
        """Return a refined mock plan string."""
        return f"[MOCK_REFINED]: {plan} — refined with incremental security controls and continuous monitoring."
