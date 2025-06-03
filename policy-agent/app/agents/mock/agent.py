from app.agents.base import Agent
from app.agents.mock.roles.rag import MockRAGRetriever
from app.agents.mock.roles.multi_path import MockMultiPathPlanner
from app.agents.mock.roles.reflection import MockSelfReflection
from app.agents.mock.roles.incremental_query import MockIncrementalQuery

class MockAgent(Agent):

    def create(self, context_id: str = None):
        print(f"[MOCK] Policy agent created by context_id={context_id}")
        return {"id": context_id or "openai-policy-session"}

    def run(self, prompt: str, context_id: str = None) -> str:
        if not self.roles:
            raise ValueError("No role has been defined within 'roles' in the MockAgent YAML.")

        current_prompt = prompt
        plans = ""

        for role in self.roles:
            role_key = next(iter(role.keys()))
            print(f"[MOCK] Executing role:{role_key}")

            if role_key == "RAG":
                retriever = MockRAGRetriever()
                current_prompt = retriever.retrieve(current_prompt)

            elif role_key == "MPG":
                planner = MockMultiPathPlanner()
                plans = planner.generate_plans(current_prompt)
                current_prompt = plans # unim tot en una cadena perquè el SRFL ho rebi tot junt

            elif role_key == "SRFL":
                reflector = MockSelfReflection()
                current_prompt = reflector.evaluate(current_prompt)

            elif role_key == "IMQ":
                refiner = MockIncrementalQuery()
                current_prompt = refiner.refine(current_prompt)

            else:
                print(f"[MOCK][WARNING] Unknown role '{role_key}', it is omitted.")

        structured_plan = plans if plans else "[Simulation] No plan generated"

        return {
            "text": f"[Generated policy simulation]: {current_prompt}",
            "structured_plan": structured_plan,
            "context_id": context_id
        }
