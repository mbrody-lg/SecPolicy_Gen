import random
from app.agents.base import Agent

class MockAgent(Agent):
    def __init__(self, name: str, instructions: str, model: str, tools: list = None, roles: list = None):
        super().__init__(name, instructions, model, tools, roles)

    def create(self, context_id: str = None):
        return {"status": "created", "context_id": context_id}

    def run(self, prompt: str, context_id: str = None) -> list:
        results = []
        for role in self.roles:
            role_id, role_config = next(iter(role.items()))
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

    def _simulate_result(self, role_id: str) -> str:
        # Distribució simulada: 50% acceptat, 30% review, 20% rebutjat
        outcomes = ["accepted", "review", "rejected"]
        weights = [0.5, 0.3, 0.2]
        return random.choices(outcomes, weights=weights, k=1)[0]
