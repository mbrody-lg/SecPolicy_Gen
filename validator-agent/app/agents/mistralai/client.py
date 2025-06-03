# app/agents/mistralai/client.py
import os
from mistralai import Mistral

class MistralClient:
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.base_url = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai/v1")
        self.client = Mistral(api_key=self.api_key)
        

    def chat(self, model: str, prompt: str, instructions: str, temperature: float, max_tokens: int):
        response = self.client.chat.complete(
            model = model,
            messages = [
                {
                    "role": "system",
                    "content": instructions
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature = temperature,
            max_tokens = max_tokens
        )
        return response
