"""Role processor that improves raw agent responses."""

from app.agents.openai.client import OpenAIClient
from app.agents.openai.structured import create_structured_chat_completion

DEFAULT_INSTRUCTIONS = """Analyze and improve this Context Agent response for clarity, structure and usefulness.

Preserve the original workflow phase and constraints from the prompt:
- If the prompt says not to draft a policy, the improved response must not draft a policy.
- If the prompt is a planning prompt, keep the output as a reviewable plan.
- If the prompt is a task-execution prompt, keep the output focused on that single task.
- If the prompt is a handoff artifact, keep it factual and structured for downstream Policy Agent/RAG use.
- Preserve explicit facts, assumptions, missing information, task ids, revision ids, and hashes.

Add compact context tags when useful, using forms such as
[context:regulation]GDPR, [context:sector]Healthcare, [context:methodology]ISO 27001.
Return only the improved response."""

OPTIMISED_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "improved_response": {"type": "string"},
        "workflow_phase": {"type": "string"},
        "preserved_constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
        "context_tags": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "improved_response",
        "workflow_phase",
        "preserved_constraints",
        "context_tags",
    ],
    "additionalProperties": False,
}

class PromptResponseOptimiser(OpenAIClient):
    """Optimize generated responses for structure and clarity."""

    def __init__(self, *, model: str = "gpt-4o-mini", instructions: str | None = None):
        """Initialize role call configuration."""
        super().__init__()
        self.model = model
        self.instructions = (instructions or DEFAULT_INSTRUCTIONS).strip()

    def execute(self, original_prompt: str, agent_response: str) -> str:
        """Return an improved response derived from prompt and output."""
        prompt = f"""
        ORIGINAL PROMPT:
        {original_prompt}
        GENERATED RESPONSE:
        {agent_response}
        """
        parsed = create_structured_chat_completion(
            chat=self.client.chat,
            model=self.model,
            messages=[
                {"role": "system", "content": self.instructions},
                {"role": "user", "content": prompt},
            ],
            schema_name="context_agent_optimised_response",
            json_schema=OPTIMISED_RESPONSE_SCHEMA,
            temperature=0.2,
            max_tokens=15000,
        )

        return parsed["improved_response"].strip()
