import os

from openai import OpenAI

class OpenAIClient:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_API_URL"),
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.chat = self.client.chat
