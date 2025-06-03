from app.agents.base import Agent
from app import mongo
from bson import ObjectId
from app.agents.mock.roles.proactive import MockProactiveGoalCreator
from app.agents.mock.roles.optimiser import MockPromptResponseOptimiser

class MockAgent(Agent):
    def create(self, context_id: str = None):
        print(f"[MOCK] Agent created by context_id={context_id}")
        return {"id": context_id or "mock-session"}

    def run(self, prompt: str, context_id: str = None) -> str:
        prompt_recieved = f"[MOCK]: {prompt}"

        # Simulem millora del prompt (proactive)
        proactive = MockProactiveGoalCreator()
        refined_prompt = proactive.execute(prompt_recieved)

        # Simulem resposta generada (aquí simplement repeteix)
        simulated_response = f"[Simulated]\n{refined_prompt}"

        # Simulem optimització (response optimiser)
        optimiser = MockPromptResponseOptimiser()
        final_output = optimiser.execute(refined_prompt, simulated_response)

        if context_id:
            mongo.db.contexts.update_one(
                {"_id": ObjectId(context_id)},
                {"$set": {
                    "status": "completed",
                    "llm_state.assistant_id": f"mock-{context_id}",
                    "llm_state.thread_id": f"mock-thread-{context_id}"
                }}
            )

        return final_output
