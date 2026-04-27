"""OpenAI-backed policy generation agent implementation."""

import logging

from app.agents.base import Agent
from app.agents.openai.client import OpenAIClient
from app.agents.roles.rag import RAGProcessor
from flask import current_app
from app.observability import build_log_event, log_event

logger = logging.getLogger(__name__)


class OpenAIAgent(Agent):
    """Run configured role chain to build policy outputs with OpenAI."""

    def __init__(self, name, instructions, model, tools=None, roles=None):
        """Initialize policy agent with OpenAI client and role config."""
        super().__init__(name, instructions, model, tools, roles)
        self.client = OpenAIClient()

    def create(self, context_id: str = None):
        """Return a lightweight backend session descriptor."""
        return {"id": context_id or "openai-policy-session"}
        
    def run(self, prompt: str, context_id: str = None, retrieval_plan=None) -> str:
        """Execute configured roles and return generated policy payload."""
        if not self.roles:
            raise ValueError("The YAML file does not contain any 'roles'.")

        current_prompt = prompt
        structured_plan = ""

        for role in self.roles:
            role_key = next(iter(role.keys()))
            instructions = role.get("instructions")
            temperature = role.get("temperature", 0.7)
            max_tokens = role.get("max_tokens", 1000)

            if not instructions:
                log_event(
                    logger,
                    logging.WARNING,
                    event="policy.openai.role_skipped",
                    stage="policy_generation",
                    context_id=context_id,
                    role=role_key,
                    reason="missing_instructions",
                )
                continue

            log_event(
                logger,
                logging.INFO,
                event="policy.openai.role_started",
                stage="policy_generation",
                context_id=context_id,
                role=role_key,
            )
            
            if role_key == "RAG":
                rag_processor = RAGProcessor(role)
                current_prompt = rag_processor.apply(
                    instructions + current_prompt,
                    retrieval_plan=retrieval_plan,
                )
                continue  # Skip direct OpenAI call for RAG stage

            if role_key == "MPG":
                proposals = role.get("proposals", 2)
                all_proposals = []

                for p in range(proposals):
                    proposal_output = self._chat(current_prompt, instructions, temperature, max_tokens)
                    all_proposals.append({
                        "id": f"proposal_{p + 1}",
                        "content": proposal_output.strip()
                    })

                # Store all proposals as structured plan
                structured_plan = all_proposals
                # Build prompt for following roles (if further refinement is needed)
                current_prompt = "\n\n".join(
                    [f"Proposal {p['id']}:\n{p['content']}" for p in all_proposals]
                )

            else:
                current_prompt = self._chat(
                    current_prompt, instructions, temperature, max_tokens
                )

            if current_app.config["DEBUG"]:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="policy.openai.role_completed",
                    stage="policy_generation",
                    context_id=context_id,
                    role=role_key,
                    prompt_length=len(current_prompt),
                )

        return {'text': current_prompt.strip(), 'structured_plan': structured_plan, "context_id": context_id}

    def _chat(self, prompt: str, instructions: str, temperature: float, max_tokens: int) -> str:
        """Run a chat completion call with role-specific instructions."""
        if current_app.config["DEBUG"]:
            log_event(
                logger,
                logging.DEBUG,
                event="policy.openai.chat_started",
                stage="policy_generation",
                prompt_length=len(prompt),
                instructions_length=len(instructions),
                temperature=temperature,
                max_tokens=max_tokens,
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
        except Exception as error:
            logger.exception(
                build_log_event(
                    event="policy.openai.chat_failed",
                    stage="policy_generation",
                    error_type=error.__class__.__name__,
                )
            )
            raise

        if current_app.config["DEBUG"]:
            log_event(
                logger,
                logging.DEBUG,
                event="policy.openai.chat_completed",
                stage="policy_generation",
                choice_count=len(getattr(response, "choices", []) or []),
            )

        return response.choices[0].message.content.strip()
