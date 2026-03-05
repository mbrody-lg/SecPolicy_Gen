"""OpenAI client wrapper for policy-agent backends."""

import os

from openai import OpenAI

class OpenAIClient:
    """Expose OpenAI chat client configured from env variables."""

    def __init__(self):
        """Initialize OpenAI SDK client with configured URL and key."""
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_API_URL"),
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.chat = self.client.chat
