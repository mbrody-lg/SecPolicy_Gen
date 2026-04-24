"""Mistral API client wrapper for validator-agent backends."""

import os
from mistralai.client import Mistral

class MistralClient:
    """Provide configured Mistral chat API access."""

    def __init__(self):
        """Initialize Mistral SDK client using environment configuration."""
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.base_url = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai/v1")
        self.client = Mistral(api_key=self.api_key)
        

    def chat(self, model: str, prompt: str, instructions: str, temperature: float, max_tokens: int):
        """Execute a chat completion call against the configured Mistral model."""
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
