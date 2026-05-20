"""Role processor that improves raw agent responses."""

from app.agents.openai.client import OpenAIClient

class PromptResponseOptimiser(OpenAIClient):
    """Optimize generated responses for structure and clarity."""

    def execute(self, original_prompt: str, agent_response: str) -> str:
        """Return an improved response derived from prompt and output."""
        instructions = """Analyze and improve this Context Agent response for clarity, structure and usefulness.

        Preserve the original workflow phase and constraints from the prompt:
        - If the prompt says not to draft a policy, the improved response must not draft a policy.
        - If the prompt is a planning prompt, keep the output as a reviewable plan.
        - If the prompt is a task-execution prompt, keep the output focused on that single task.
        - If the prompt is a handoff artifact, keep it factual and structured for downstream Policy Agent/RAG use.
        - Preserve explicit facts, assumptions, missing information, task ids, revision ids, and hashes.

        Add compact context tags when useful, using forms such as
        [context:regulation]GDPR, [context:sector]Healthcare, [context:methodology]ISO 27001.
        Return only the improved response."""
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
            max_tokens= 15000
        )

        return response.choices[0].message.content.strip()
