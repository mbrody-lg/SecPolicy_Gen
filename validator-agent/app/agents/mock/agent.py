"""Mock validator agent used for local and test execution paths."""

import random
from typing import Dict, List, Optional
from app.agents.base import Agent

class MockAgent(Agent):
    """Simulate validator role outcomes without calling external providers."""

    def __init__(self, name: str, instructions: str, model: str, tools: list = None, roles: list = None):
        """Initialize mock agent using shared base configuration."""
        super().__init__(name, instructions, model, tools, roles)

    def create(self, context_id: str = None):
        """Return synthetic creation metadata for the given context."""
        return {"status": "created", "context_id": context_id}

    def run(
        self,
        prompt: str,
        context_id: str = None,
        only_roles: Optional[List[Dict]] = None,
    ) -> list:
        """Generate simulated role-by-role validation responses."""
        results = []
        selected_roles = only_roles if only_roles else self.roles

        for role in selected_roles:
            role_id, _role_config = next(iter(role.items()))
            simulated_result = self._simulate_result(role_id)

            result = {
                "role": role_id,
                "status": simulated_result,
                "context_id": context_id,
            }

            if simulated_result == "accepted":
                result.update({
                    "text": [
                        {
                            "title": "Asset management",
                            "summary": "Ensure effective control of information assets.",
                            "steps": [
                                "Create and maintain an asset inventory.",
                                "Classify assets according to risk and value.",
                                "Assign owners to each asset."
                            ],
                            "references": [
                                {"source": "ISO 27001:2022", "section": "8"},
                                {"source": "GDPR", "article": "32"}
                            ]
                        }
                    ]
                })
            elif simulated_result == "review":
                result.update({
                    "reasons": "Lack of consensus among validating agents.",
                    "recommendations": [
                        "Clarify the tone in section 2.",
                        "Add more justification to the asset classification step."
                    ]
                })
            elif simulated_result == "rejected":
                result.update({
                    "reasons": "References to ISO controls are missing in the classification section.",
                    "recommendations": [
                        "Include ISO 27001:2022 control 8 explicitly.",
                        "Map each asset to a control requirement."
                    ]
                })

            results.append(result)
        return results

    def _simulate_result(self, _role_id: str) -> str:
        """Sample a simulated validation status for a role."""
        # Simulated distribution: 50% accepted, 30% review, 20% rejected
        outcomes = ["accepted", "review", "rejected"]
        weights = [0.5, 0.3, 0.2]
        return random.choices(outcomes, weights=weights, k=1)[0]
