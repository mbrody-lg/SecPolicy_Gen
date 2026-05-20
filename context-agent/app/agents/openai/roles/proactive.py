"""Role processor that proactively rewrites user context objectives."""

from app.agents.openai.client import OpenAIClient

class ProactiveGoalCreator(OpenAIClient):
    """Generate an improved goal prompt before assistant execution."""

    def execute(self, input_prompt: str) -> str:
        """Return an enhanced objective prompt using chat completion."""
        instructions = """
        Improve this Context Agent prompt without changing its workflow phase.
        Context Agent works inside Context Workplace. Do not draft a policy.

        Rules:
        - Preserve the phase intent exactly: INTAKE, CONTEXT UPDATE, PLANNING, EXECUTION, or Policy Agent handoff.
        - Preserve explicit user facts, field names, task ids, revision ids, hashes, and output constraints.
        - Strengthen the prompt so the answer is concrete for information-security context analysis.
        - Keep missing information as questions or assumptions; do not invent facts.
        - Do not ask the model to develop, write, validate, or approve a policy.
        - Do not replace a task-execution prompt with a general consulting answer.
        - Return only the improved prompt text.
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_prompt}
            ],
        temperature = 0.7,
        max_tokens = 15000
        )
        return response.choices[0].message.content.strip()
