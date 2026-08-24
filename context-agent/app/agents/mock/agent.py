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

    def run_structured(
        self,
        _prompt: str,
        *,
        schema_name: str,
        json_schema: dict,
        context_id: str = None,
    ) -> dict:
        """Return compact deterministic fixtures for structured workflow phases."""
        _ = json_schema, context_id
        empty_hints = {
            "collection_families": [],
            "jurisdictions": [],
            "sectors": [],
            "methodologies": [],
            "query_terms": [],
        }
        if schema_name == "context_agent_task_result":
            return {
                "task_id": "mock-context-task",
                "status": "completed",
                "findings": ["The approved security-context task was assessed."],
                "assumptions": [],
                "missing_details": [],
                "risks": ["Control implementation should be verified during policy review."],
                "policy_implications": ["Define ownership, evidence, and review cadence."],
                "rag_retrieval_hints": {
                    **empty_hints,
                    "collection_families": ["controls"],
                    "query_terms": ["security controls"],
                },
            }
        if schema_name == "context_agent_planning_review":
            return {
                "plan_summary": "The deterministic context plan is ready for review.",
                "tasks": [],
                "missing_context_questions": [],
                "approval_recommendation": "review_required",
            }
        if schema_name == "context_agent_context_building_review":
            return {
                "summary": "The deterministic security context was reviewed.",
                "explicit_facts": [],
                "assumptions": [],
                "missing_information": [],
                "follow_up_questions": [],
                "security_domains": [],
                "rag_retrieval_hints": empty_hints,
                "next_action": "review_required",
            }
        raise ValueError(f"Unsupported mock structured schema: {schema_name}")
