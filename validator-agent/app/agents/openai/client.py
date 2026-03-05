"""OpenAI client wrapper for validator-agent backends."""

import os

from openai import OpenAI

class OpenAIClient:
    """Provide configured OpenAI chat client access."""

    def __init__(self):
        """Initialize OpenAI SDK client from environment configuration."""
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_API_URL"),
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.chat = self.client.chat
