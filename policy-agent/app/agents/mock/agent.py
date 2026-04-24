"""Mock policy-agent backend used for deterministic local testing."""

import logging

from app.agents.base import Agent
from app.agents.mock.roles.rag import MockRAGRetriever
from app.agents.mock.roles.multi_path import MockMultiPathPlanner
from app.agents.mock.roles.reflection import MockSelfReflection
from app.agents.mock.roles.incremental_query import MockIncrementalQuery
from app.observability import log_event

logger = logging.getLogger(__name__)

class MockAgent(Agent):
    """Simulate role-based policy generation without external APIs."""

    def create(self, context_id: str = None):
        """Return a simulated session descriptor for the context."""
        log_event(
            logger,
            logging.INFO,
            event="policy.mock_agent.created",
            stage="policy_generation",
            context_id=context_id,
        )
        return {"id": context_id or "openai-policy-session"}

    def run(self, prompt: str, context_id: str = None) -> str:
        """Run the mocked role pipeline and return simulated policy output."""
        if not self.roles:
            raise ValueError("No role has been defined within 'roles' in the MockAgent YAML.")

        current_prompt = prompt
        plans = ""

        for role in self.roles:
            role_key = next(iter(role.keys()))
            log_event(
                logger,
                logging.INFO,
                event="policy.mock_agent.role_started",
                stage="policy_generation",
                context_id=context_id,
                role=role_key,
            )

            if role_key == "RAG":
                retriever = MockRAGRetriever()
                current_prompt = retriever.retrieve(current_prompt)

            elif role_key == "MPG":
                planner = MockMultiPathPlanner()
                plans = planner.generate_plans(current_prompt)
                current_prompt = plans  # merge into one payload so SRFL receives full context

            elif role_key == "SRFL":
                reflector = MockSelfReflection()
                current_prompt = reflector.evaluate(current_prompt)

            elif role_key == "IMQ":
                refiner = MockIncrementalQuery()
                current_prompt = refiner.refine(current_prompt)

            else:
                log_event(
                    logger,
                    logging.WARNING,
                    event="policy.mock_agent.role_skipped",
                    stage="policy_generation",
                    context_id=context_id,
                    role=role_key,
                    reason="unknown_role",
                )

        structured_plan = plans if plans else "[Simulation] No plan generated"

        return {
            "text": f"[Generated policy simulation]: {current_prompt}",
            "structured_plan": structured_plan,
            "context_id": context_id
        }
