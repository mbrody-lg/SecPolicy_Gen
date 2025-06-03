from app.agents.base import Agent
from app.agents.openai.client import OpenAIClient
from app.agents.openai.roles.proactive import ProactiveGoalCreator
from app.agents.openai.roles.optimiser import PromptResponseOptimiser
from app import mongo
from bson import ObjectId
import time

class OpenAIAgent(Agent):
    def __init__(self, name, instructions, model, tools=[]):
        Agent.__init__(self, name, instructions, model, tools)
        self.client = OpenAIClient()
        self.assistant_id = None

    def create(self, context_id: str = None):
        # Si ja existeix un agent per aquest context, el recuperem de Mongo
        if context_id:
            doc = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
            state = doc.get("llm_state", {}) if doc else {}
            self.assistant_id = state.get("assistant_id")

        # Si no existeix, el creem
        if not self.assistant_id:
            assistant = self.client.beta.assistants.create(
                name=self.name,
                instructions=self.instructions,
                model=self.model,
                tools=self.tools
            )
            self.assistant_id = assistant.id
            if context_id:
                mongo.db.contexts.update_one(
                    {"_id": ObjectId(context_id)},
                    {"$set": {"llm_state.assistant_id": self.assistant_id}}
                )
        return {"assistant_id": self.assistant_id}

    def run(self, prompt: str, context_id: str = None) -> str:
        # Millora del prompt (proactive)
        proactive = ProactiveGoalCreator()
        refined_prompt = proactive.execute(prompt)

        # Recupera thread_id si existeix
        doc = mongo.db.contexts.find_one({"_id": ObjectId(context_id)}) if context_id else {}
        thread_id = doc.get("llm_state", {}).get("thread_id") if doc else None

        # Si no hi ha thread_id, en creem un nou
        if not thread_id:
            thread = self.client.beta.threads.create()
            thread_id = thread.id
            # Guardar thread_id a Mongo per futures execucions
            if context_id:
                mongo.db.contexts.update_one(
                    {"_id": ObjectId(context_id)},
                    {"$set": {"llm_state.thread_id": thread_id}}
                )

        # Afegeix el prompt com a nou missatge
        self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=prompt
        )

        # Executa el prompt refinat
        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=self.assistant_id
        )

        # Espera resultats
        while True:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run.status == "completed":
                break
            elif run.status in ("failed", "cancelled"):
                raise RuntimeError("OpenAI Run failed or cancelled.")
            time.sleep(0.5)

        # Recupera resposta
        messages = self.client.beta.threads.messages.list(thread_id=thread_id)
        raw_response = messages.data[0].content[0].text.value

        # Millora la resposta rebuda
        optimiser = PromptResponseOptimiser()
        result = optimiser.execute(refined_prompt, raw_response)

        if context_id:
            mongo.db.contexts.update_one(
                {"_id": ObjectId(context_id)},
                {"$set": {
                    "status": "completed",
                    "refined_prompt": refined_prompt,
                    "response": result,
                    "assistant_id": self.assistant_id,
                    "thread_id": thread_id
                }}
            )

        return result