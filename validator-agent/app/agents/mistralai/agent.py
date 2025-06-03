from app.agents.base import Agent
from app.agents.mistralai.client import MistralClient
from flask import current_app
from typing import List, Dict, Optional
import yaml 

class MistralAIAgent(Agent):
    def __init__(self, name: str, instructions: str, model: str, tools: list = None, roles: list = None):
        super().__init__(name, instructions, model, tools, roles)
        self.client = MistralClient()
        self.debug_mode = current_app.config.get("DEBUG", False)

        config_path = current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            self.prompt_template = config["agent"].get("prompt_template")

    def create(self, context_id: str = None):
        return {"status": "created", "context_id": context_id}

    def run(self, prompt: str, context_id: str = None, only_roles: Optional[List[Dict]] = None) -> List[Dict]:
        selected_roles = only_roles if only_roles else self.roles
        
        if self.debug_mode:
            print(f"DEBUG_SELECTED_ROLES: {selected_roles}")

        results = []
        
        for role_config in selected_roles:
            role_key = next(iter(role_config))

            instructions = role_config.get("instructions", self.instructions)
            temperature = role_config.get("temperature", 0.7)
            max_tokens = role_config.get("max_tokens", 1000)
            
            if self.debug_mode:
                print(f"[MistraAIAgent] Executant rol: {role_key}\n")
                print(f"[Prompt]\n{prompt}\n")

            try:
                
                response = self.client.chat(
                    model=self.model,
                    prompt=prompt,
                    instructions=instructions,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

            
                content = response.choices[0].message.content.strip()
                parsed = self.parse_response_content(content)
                
                if self.debug_mode:
                    print(f'RESPONSE: {response}')
                    print(f"CONTENT: {content}")
                    print(f"PARSED: {parsed}")

                results.append({
                    "role": role_key,
                    "status":  parsed["status"],
                    "text": content,
                    "reason": parsed["reason"],
                    "recommendations": parsed["recommendations"]
                })
            
            except Exception as e:
                if self.debug_mode:
                    print(f"[LOGGING ERROR] {str(e)}")
                    print(f'"role": {role_key},"status": {parsed["status"]},"text": {content},"reason": {parsed["reason"]},"recommendations": {parsed["recommendations"]}')

        if self.debug_mode:
            print(f"RESULTS: {results}")

        return results
