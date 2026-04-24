"""Mock agent backend for deterministic local context testing."""

import logging

from bson import ObjectId

from app import mongo
from app.agents.base import Agent
from app.agents.mock.roles.proactive import MockProactiveGoalCreator
from app.agents.mock.roles.optimiser import MockPromptResponseOptimiser
from app.observability import log_event

logger = logging.getLogger(__name__)

class MockAgent(Agent):
    """Mock implementation that simulates prompt processing pipeline."""

    def create(self, context_id: str = None):
        """Simulate backend initialization for a context."""
        log_event(
            logger,
            logging.INFO,
            event="context.mock_agent.created",
            stage="context_generation",
            context_id=context_id,
        )
        return {"id": context_id or "mock-session"}

    def run(self, prompt: str, context_id: str = None) -> str:
        """Run the mocked proactive and optimizer pipeline."""
        prompt_recieved = f"[MOCK]: {prompt}"

        # Simulate proactive prompt improvement
        proactive = MockProactiveGoalCreator()
        refined_prompt = proactive.execute(prompt_recieved)

        # Simulate generated response (simple echo)
        simulated_response = f"[Simulated]\n{refined_prompt}"

        # Simulate response optimization
        optimiser = MockPromptResponseOptimiser()
        final_output = optimiser.execute(refined_prompt, simulated_response)

        if context_id:
            mongo.db.contexts.update_one(
                {"_id": ObjectId(context_id)},
                {"$set": {
                    "status": "completed",
                    "refined_prompt": refined_prompt,
                    "llm_state.assistant_id": f"mock-{context_id}",
                    "llm_state.thread_id": f"mock-thread-{context_id}"
                }}
            )

        return final_output
