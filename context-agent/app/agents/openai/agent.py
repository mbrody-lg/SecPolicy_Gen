"""OpenAI-backed agent implementation for context generation."""

import time

from bson import ObjectId

from app import mongo
from app.agents.base import Agent
from app.agents.openai.client import OpenAIClient
from app.agents.openai.roles.optimiser import PromptResponseOptimiser
from app.agents.openai.roles.proactive import ProactiveGoalCreator
from app.agents.openai.structured import (
    ProviderConnectivityError,
    ProviderIncompleteError,
    ProviderRequest,
    ProviderRateLimitError,
    ProviderTimeoutError,
    create_structured_provider_call,
)


_ASSISTANT_PENDING_STATUSES = {"queued", "in_progress", "cancelling"}
_ASSISTANT_INCOMPLETE_STATUSES = {"expired", "incomplete", "requires_action"}


def _safe_run_detail(value) -> str | None:
    """Return a bounded run diagnostic value without raw provider text."""
    if value is None:
        return None
    text = str(value)
    return text[:80] if text else None


def _assistant_run_error(run, *, model: str) -> Exception:
    """Map Assistants run terminal states to bounded provider errors."""
    status = _safe_run_detail(getattr(run, "status", None)) or "unknown"
    last_error = getattr(run, "last_error", None)
    last_error_code = _safe_run_detail(getattr(last_error, "code", None))
    incomplete_details = getattr(run, "incomplete_details", None)
    incomplete_reason = _safe_run_detail(getattr(incomplete_details, "reason", None))
    details = {"run_status": status}
    if last_error_code:
        details["last_error_code"] = last_error_code
    if incomplete_reason:
        details["incomplete_reason"] = incomplete_reason

    if last_error_code == "rate_limit_exceeded":
        return ProviderRateLimitError(
            phase="assistant_run",
            schema_name="assistant_run",
            model=model,
            api_mode="assistants",
            details=details,
        )
    if status in _ASSISTANT_INCOMPLETE_STATUSES:
        return ProviderIncompleteError(
            phase="assistant_run",
            schema_name="assistant_run",
            model=model,
            api_mode="assistants",
            details=details,
        )
    return ProviderConnectivityError(
        phase="assistant_run",
        schema_name="assistant_run",
        model=model,
        api_mode="assistants",
        details=details,
    )


class OpenAIAgent(Agent):
    """Concrete agent that uses OpenAI Assistants and role processors."""

    def __init__(self, name, instructions, model, tools=None, role_instructions=None):
        """Initialize OpenAI agent state and lazily created assistant id."""
        Agent.__init__(self, name, instructions, model, tools or [])
        self.client = OpenAIClient()
        self.assistant_id = None
        self.role_instructions = role_instructions or {}

    def create(self, context_id: str = None):
        """Create or recover an assistant bound to the provided context."""
        # If an assistant already exists for this context, recover it from Mongo
        if context_id:
            doc = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
            state = doc.get("llm_state", {}) if doc else {}
            self.assistant_id = state.get("assistant_id")

        # Otherwise, create it
        if not self.assistant_id:
            assistant = self.client.beta.assistants.create(
                name=self.name,
                instructions=self.instructions,
                model=self.model,
                tools=self.tools
            )
            self.assistant_id = assistant.id
            if context_id:
                mongo.db.contexts.update_one(
                    {"_id": ObjectId(context_id)},
                    {"$set": {"llm_state.assistant_id": self.assistant_id}}
                )
        return {"assistant_id": self.assistant_id}

    def run(self, prompt: str, context_id: str = None) -> str:
        """Run context generation lifecycle and persist outputs in Mongo."""
        # Improve prompt proactively
        proactive = ProactiveGoalCreator(
            model=self.model,
            instructions=self.role_instructions.get("proactive_goal_creator"),
        )
        refined_prompt = proactive.execute(prompt)

        # Recover thread_id when available
        doc = mongo.db.contexts.find_one({"_id": ObjectId(context_id)}) if context_id else {}
        thread_id = doc.get("llm_state", {}).get("thread_id") if doc else None

        # If there is no thread_id, create a new one
        if not thread_id:
            thread = self.client.beta.threads.create()
            thread_id = thread.id
            # Store thread_id in Mongo for future runs
            if context_id:
                mongo.db.contexts.update_one(
                    {"_id": ObjectId(context_id)},
                    {"$set": {"llm_state.thread_id": thread_id}}
                )

        # Add the prompt as a new user message
        self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=refined_prompt
        )

        # Execute the run
        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=self.assistant_id
        )

        # Wait for completion with a bounded legacy Assistants polling loop.
        deadline = time.monotonic() + self.client.timeout_seconds
        while True:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run.status == "completed":
                break
            if run.status not in _ASSISTANT_PENDING_STATUSES:
                raise _assistant_run_error(run, model=self.model)
            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    phase="assistant_run",
                    schema_name="assistant_run",
                    model=self.model,
                    api_mode="assistants",
                    details={"last_status": _safe_run_detail(run.status) or "unknown"},
                )
            time.sleep(0.5)

        # Retrieve assistant response
        messages = self.client.beta.threads.messages.list(thread_id=thread_id)
        raw_response = messages.data[0].content[0].text.value

        # Improve returned response
        optimiser = PromptResponseOptimiser(
            model=self.model,
            instructions=self.role_instructions.get("response_optimiser"),
        )
        result = optimiser.execute(refined_prompt, raw_response)

        if context_id:
            mongo.db.contexts.update_one(
                {"_id": ObjectId(context_id)},
                {"$set": {
                    "status": "completed",
                    "refined_prompt": refined_prompt,
                    "response": result,
                    "assistant_id": self.assistant_id,
                    "thread_id": thread_id
                }}
            )

        return result

    def run_structured(
        self,
        prompt: str,
        *,
        schema_name: str,
        json_schema: dict,
        context_id: str = None,
    ) -> dict:
        """Run a single structured Context Agent call without Assistant threads."""
        proactive = ProactiveGoalCreator(
            model=self.model,
            instructions=self.role_instructions.get("proactive_goal_creator"),
        )
        refined_prompt = proactive.execute(prompt)

        return create_structured_provider_call(
            chat=self.client.chat,
            responses=self.client.responses,
            request=ProviderRequest(
                model=self.model,
                api_mode=self.client.structured_api_mode,
                messages=[
                    {"role": "system", "content": self.instructions},
                    {"role": "user", "content": refined_prompt},
                ],
                schema_name=schema_name,
                json_schema=json_schema,
                phase=schema_name,
                temperature=0.2,
                max_tokens=15000,
            ),
        )
