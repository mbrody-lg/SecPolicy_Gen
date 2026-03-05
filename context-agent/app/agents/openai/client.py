"""OpenAI client wrapper for context-agent roles."""

import os

from openai import OpenAI

class OpenAIClient:
    """Thin wrapper exposing OpenAI chat and beta APIs."""

    def __init__(self):
        """Initialize OpenAI SDK client from environment variables."""
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_API_URL"),
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.chat = self.client.chat
        self.beta = self.client.beta
