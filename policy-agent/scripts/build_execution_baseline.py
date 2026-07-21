#!/usr/bin/env python3
"""Build a deterministic snapshot of the current Policy Agent call chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from flask import Flask

from app.agents.openai.agent import OpenAIAgent


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "app" / "config" / "policy_agent.yaml"
BASELINE_CONTEXT_ID = "policy-baseline-context"
BASELINE_PROMPT = "Generate the deterministic policy execution baseline."
UPDATE_PROMPT = "Revise the deterministic policy execution baseline."


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeterministicProvider:
    """OpenAI-shaped fake that records calls without network access."""

    def __init__(self, responses: list[str], failure_categories: dict[int, str] | None = None):
        self.responses = responses
        self.failure_categories = failure_categories or {}
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        call_number = len(self.calls) + 1
        failure_category = self.failure_categories.get(call_number)
        response_text = None if failure_category else self.responses[call_number - 1]
        usage = {
            "input_tokens": 100 + call_number,
            "output_tokens": 50 + call_number,
            "cached_tokens": 0,
            "total_tokens": 150 + (2 * call_number),
        }
        self.calls.append(
            {
                "model": kwargs["model"],
                "messages": kwargs["messages"],
                "temperature": kwargs["temperature"],
                "max_tokens": kwargs["max_tokens"],
                "usage": usage,
                "latency_ms": float(5 + call_number),
                "failure_category": failure_category,
                "response": response_text,
            }
        )
        if failure_category:
            raise RuntimeError(failure_category)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_text))],
            usage=SimpleNamespace(**usage),
        )


class DeterministicRAGProcessor:
    """Avoid vector access while preserving the configured RAG pipeline step."""

    def __init__(self, _role):
        self.evidence_items = []

    def apply(self, query: str, **_kwargs) -> str:
        return f"[deterministic-rag]\n{query}"


def _create_agent(config: dict, provider: DeterministicProvider) -> OpenAIAgent:
    with patch("app.agents.openai.agent.OpenAIClient", return_value=provider):
        return OpenAIAgent(
            name=config["name"],
            instructions=config["instructions"],
            model=config["model"],
            roles=config["roles"],
        )


def _normalized_run(provider: DeterministicProvider) -> dict:
    invocations = []
    for index, call in enumerate(provider.calls, start=1):
        invocations.append(
            {
                "index": index,
                "model": call["model"],
                "messages": [
                    {
                        "role": message["role"],
                        "content_length": len(message["content"]),
                        "content_sha256": _digest(message["content"]),
                    }
                    for message in call["messages"]
                ],
                "settings": {
                    "temperature": call["temperature"],
                    "max_tokens": call["max_tokens"],
                },
                "usage": call["usage"],
                "latency_ms": call["latency_ms"],
                "failure_category": call["failure_category"],
                "response_length": len(call["response"] or ""),
                "response_sha256": _digest(call["response"] or ""),
            }
        )
    return {
        "logical_calls": len(invocations),
        "configured_output_token_ceiling": sum(
            invocation["settings"]["max_tokens"] for invocation in invocations
        ),
        "usage": {
            key: sum(invocation["usage"][key] for invocation in invocations)
            for key in ("input_tokens", "output_tokens", "cached_tokens", "total_tokens")
        },
        "invocations": invocations,
    }


def build_execution_baseline(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Execute initial and update role chains against deterministic providers."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    app = Flask("policy-execution-baseline")
    app.config["DEBUG"] = False

    generation_provider = DeterministicProvider(
        ["proposal-one", "proposal-two", "proposal-three", "combined", "final-policy"]
    )
    update_provider = DeterministicProvider(["revised-policy"])

    with app.app_context(), patch(
        "app.agents.openai.agent.RAGProcessor", DeterministicRAGProcessor
    ):
        generation_agent = _create_agent(config, generation_provider)
        generation_agent.run(BASELINE_PROMPT, context_id=BASELINE_CONTEXT_ID)

        update_agent = _create_agent(config, update_provider)
        update_agent.roles = [update_agent.roles[-1]]
        update_agent.run(UPDATE_PROMPT, context_id=BASELINE_CONTEXT_ID)

    return {
        "schema_version": "policy_execution_baseline.v1",
        "source": {
            "config": str(config_path.relative_to(ROOT)),
            "agent_type": config["type"],
            "global_model": config["model"],
            "latency_mode": "deterministic_fake",
            "usage_mode": "deterministic_fake",
        },
        "generation": _normalized_run(generation_provider),
        "update": _normalized_run(update_provider),
    }


if __name__ == "__main__":
    print(json.dumps(build_execution_baseline(), indent=2, sort_keys=True))
