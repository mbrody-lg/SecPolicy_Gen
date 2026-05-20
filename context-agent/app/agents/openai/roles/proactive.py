"""Role processor that proactively rewrites user context objectives."""

from app.agents.openai.client import OpenAIClient
from app.agents.openai.structured import create_structured_chat_completion

DEFAULT_INSTRUCTIONS = """
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

PROACTIVE_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "improved_prompt": {"type": "string"},
        "workflow_phase": {"type": "string"},
        "preserved_constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["improved_prompt", "workflow_phase", "preserved_constraints"],
    "additionalProperties": False,
}

class ProactiveGoalCreator(OpenAIClient):
    """Generate an improved goal prompt before assistant execution."""

    def __init__(self, *, model: str = "gpt-4o-mini", instructions: str | None = None):
        """Initialize role call configuration."""
        super().__init__()
        self.model = model
        self.instructions = (instructions or DEFAULT_INSTRUCTIONS).strip()

    def execute(self, input_prompt: str) -> str:
        """Return an enhanced objective prompt using chat completion."""
        parsed = create_structured_chat_completion(
            chat=self.client.chat,
            model=self.model,
            messages=[
                {"role": "system", "content": self.instructions},
                {"role": "user", "content": input_prompt},
            ],
            schema_name="context_agent_proactive_prompt",
            json_schema=PROACTIVE_PROMPT_SCHEMA,
            phase="context_prompt_refinement",
            temperature=0.2,
            max_tokens=15000,
        )
        return parsed["improved_prompt"].strip()
