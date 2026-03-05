"""Role processor that improves raw agent responses."""

from app.agents.openai.client import OpenAIClient

class PromptResponseOptimiser(OpenAIClient):
    """Optimize generated responses for structure and clarity."""

    def execute(self, original_prompt: str, agent_response: str) -> str:
        """Return an improved response derived from prompt and output."""
        instructions = """ Analyze and improve this agent response for clarity, structure and usefulness.
        Give an improved version and define one or more context tags among the possible ones
        (regulation, sector, methodology, guide, language) example: [context: regulation]LOPDGDD, [context:methodology]ISO 27001 """
        prompt = f"""
        ORIGINAL PROMPT:
        {original_prompt}
        GENERATED RESPONSE:
        {agent_response}
        """

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt}
            ],
            temperature= 0.7,
            max_tokens= 2000
        )
        return response.choices[0].message.content.strip()
