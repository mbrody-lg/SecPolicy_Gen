import os
from app.agents.base import Agent
from app.agents.openai.client import OpenAIClient
from app.agents.roles.rag import RAGProcessor
from flask import current_app


class OpenAIAgent(Agent):

    def __init__(self, name, instructions, model, tools=None, roles=None):
        super().__init__(name, instructions, model, tools, roles)
        self.client = OpenAIClient()

    def create(self, context_id: str = None):
        return {"id": context_id or "openai-policy-session"}
        
    def run(self, prompt: str, context_id: str = None) -> str:
        if not self.roles:
            raise ValueError("The YAML file does not contain any 'roles'.")

        current_prompt = prompt
        structured_plan = ""

        for role in self.roles:
            role_key = next(iter(role.keys()))
            instructions = role.get("instructions")
            temperature = role.get("temperature", 0.7)
            max_tokens = role.get("max_tokens", 1000)

            if not instructions:
                print(f"[WARNING] Role '{role_key}' has no instructions. It is skipped.")
                continue

            print(f"[INFO] Running role: {role_key}")
            
            if role_key == "RAG":
                rag_processor = RAGProcessor(role)
                current_prompt = rag_processor.apply(instructions + current_prompt)
                continue  # No passem per OpenAI aquí
    
            current_prompt = self._chat(current_prompt, instructions, temperature, max_tokens)
            
          
            if role_key == "MPG":
                proposals = role.get("proposals", 2)
                all_proposals = []

                for p in range(proposals):
                    proposal_output = self._chat(current_prompt, instructions, temperature, max_tokens)
                    all_proposals.append({
                        "id": f"proposal_{p + 1}",
                        "content": proposal_output.strip()
                    })

                # Guardem com a pla estructurat totes les propostes
                structured_plan = all_proposals
                # Preparem prompt per següents rols (si calen refinaments posteriors)
                current_prompt = "\n\n".join(
                    [f"Proposal {p['id']}:\n{p['content']}" for p in all_proposals]
                )
                
            else:
                current_prompt = self._chat(current_prompt, instructions, temperature, max_tokens)            

            if current_app.config["DEBUG"]:
                print(current_prompt)

        return {'text': current_prompt.strip(), 'structured_plan': structured_plan, "context_id": context_id}

    def _chat(self, prompt: str, instructions: str, temperature: float, max_tokens: int) -> str:
        
        if current_app.config["DEBUG"]:
            print(f"prompt: {prompt}\n instructions:{instructions}\n temperature: {temperature}\n max_tokens: {max_tokens}")
        
        try:        
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
        except Exception as e:
            print({"error": str(e)})

        if current_app.config["DEBUG"]:
            print(f"response: {response}")

        return response.choices[0].message.content.strip()
