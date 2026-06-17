import json
from types import SimpleNamespace

import pytest

from app.agents import factory
from app.agents.base import AGENT_REGISTRY
from app.agents.openai import client as client_module
from app.agents.openai.roles.optimiser import PromptResponseOptimiser
from app.agents.openai.roles.proactive import ProactiveGoalCreator
from app.agents.openai.structured import (
    ProviderCallError,
    ProviderConnectivityError,
    ProviderIncompleteError,
    ProviderRequest,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderSchemaMismatchError,
    ProviderTimeoutError,
    StructuredOutputError,
    create_structured_chat_completion,
    create_structured_provider_call,
)


class FakeRateLimitError(Exception):
    status_code = 429


class FakeCompletions:
    def __init__(self, payload=None, *, refusal=None, content=None, error=None, response=None):
        self.payloads = list(payload) if isinstance(payload, list) else [payload or {}]
        self.refusal = refusal
        self.content = content
        self.error = error
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if self.response is not None:
            return self.response
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        content = self.content if self.content is not None else json.dumps(payload)
        message = SimpleNamespace(content=content, refusal=self.refusal)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeResponses:
    def __init__(self, payload=None, *, status="completed", output=None, error=None):
        self.payloads = (
            list(payload) if isinstance(payload, list) else [payload or {"answer": "ok"}]
        )
        self.status = status
        self.output = output or []
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return SimpleNamespace(
            status=self.status,
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            output_text=json.dumps(payload),
            output=self.output,
        )


class FakeOpenAI:
    completions = FakeCompletions()
    responses = FakeResponses()

    def __init__(self, *, base_url, api_key, timeout=None):
        self.chat = FakeChat(self.completions)
        self.beta = SimpleNamespace()
        self.responses = self.__class__.responses
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout


def install_fake_openai(monkeypatch, completions, responses=None):
    FakeOpenAI.completions = completions
    FakeOpenAI.responses = responses or FakeResponses()
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_URL", "https://openai.example.test/v1")
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)


def test_structured_chat_completion_sends_strict_json_schema():
    completions = FakeCompletions({"answer": "ok"})

    result = create_structured_chat_completion(
        chat=FakeChat(completions),
        model="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        schema_name="test_schema",
        json_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )

    assert result == {"answer": "ok"}
    call = completions.calls[0]
    assert call["model"] == "gpt-test"
    assert call["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


def test_provider_request_rejects_retention_and_background_modes():
    base = {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hello"}],
        "schema_name": "test_schema",
        "json_schema": {"type": "object"},
    }

    with pytest.raises(ValueError, match="store=false"):
        ProviderRequest(**base, store=True)

    with pytest.raises(ValueError, match="background=false"):
        ProviderRequest(**base, background=True)


def test_structured_responses_call_sends_strict_schema_without_retention():
    responses = FakeResponses({"answer": "ok"})

    result = create_structured_provider_call(
        responses=responses,
        request=ProviderRequest(
            api_mode="responses",
            model="gpt-test",
            messages=[
                {"role": "system", "content": "system instructions"},
                {"role": "user", "content": "hello"},
            ],
            schema_name="test_schema",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            max_tokens=500,
        ),
    )

    assert result == {"answer": "ok"}
    call = responses.calls[0]
    assert call["input"] == [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "hello"},
    ]
    assert call["store"] is False
    assert call["background"] is False
    assert call["max_output_tokens"] == 500
    assert call["text"] == {
        "format": {
            "type": "json_schema",
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


def test_structured_responses_rejects_refusal():
    refusal = SimpleNamespace(type="refusal", refusal="not allowed")
    message = SimpleNamespace(type="message", content=[refusal])
    responses = FakeResponses(output=[message])

    with pytest.raises(ProviderRefusalError) as exc_info:
        create_structured_provider_call(
            responses=responses,
            request=ProviderRequest(
                api_mode="responses",
                model="gpt-test",
                messages=[{"role": "user", "content": "hello"}],
                schema_name="test_schema",
                json_schema={"type": "object"},
            ),
        )

    assert exc_info.value.to_diagnostic()["api_mode"] == "responses"


def test_structured_responses_maps_incomplete_output():
    responses = FakeResponses(status="incomplete")

    with pytest.raises(ProviderIncompleteError) as exc_info:
        create_structured_provider_call(
            responses=responses,
            request=ProviderRequest(
                api_mode="responses",
                model="gpt-test",
                messages=[{"role": "user", "content": "hello"}],
                schema_name="test_schema",
                json_schema={"type": "object"},
            ),
        )

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["api_mode"] == "responses"
    assert diagnostic["details"] == {"reason": "max_output_tokens"}


def test_structured_chat_completion_rejects_refusal():
    completions = FakeCompletions(refusal="not allowed")

    with pytest.raises(ProviderRefusalError, match="refused") as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            phase="context_building",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    assert exc_info.value.to_diagnostic() == {
        "provider": "openai",
        "api_mode": "chat_completions",
        "error_type": "provider_refusal",
        "error_code": "openai_refusal",
        "safe_message": "OpenAI refused the structured output request.",
        "status_code": 422,
        "retryable": False,
        "phase": "context_building",
        "schema_name": "test_schema",
        "model": "gpt-test",
        "details": {},
    }


def test_structured_chat_completion_rejects_empty_content_as_incomplete():
    completions = FakeCompletions(content="")

    with pytest.raises(ProviderIncompleteError) as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            phase="planning",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    assert exc_info.value.retryable is True
    assert exc_info.value.to_diagnostic()["error_code"] == "openai_incomplete_response"
    assert exc_info.value.to_diagnostic()["status_code"] == 502


def test_structured_chat_completion_rejects_missing_message_as_incomplete():
    completions = FakeCompletions(response=SimpleNamespace(choices=[]))

    with pytest.raises(ProviderIncompleteError) as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["error_code"] == "openai_incomplete_response"
    assert diagnostic["model"] == "gpt-test"


def test_structured_chat_completion_rejects_invalid_json_as_schema_mismatch():
    completions = FakeCompletions(content="not-json")

    with pytest.raises(ProviderSchemaMismatchError) as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            phase="task_execution",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    assert exc_info.value.to_diagnostic()["phase"] == "task_execution"
    assert exc_info.value.to_diagnostic()["error_code"] == "openai_schema_mismatch"


def test_structured_chat_completion_maps_timeout_to_bounded_error():
    completions = FakeCompletions(error=TimeoutError("raw timeout detail"))

    with pytest.raises(ProviderTimeoutError) as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            phase="final_context",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["retryable"] is True
    assert diagnostic["status_code"] == 504
    assert diagnostic["error_code"] == "openai_timeout"
    assert diagnostic["safe_message"] == "OpenAI structured output request timed out."
    assert "raw timeout detail" not in str(diagnostic)


def test_structured_chat_completion_maps_rate_limit_to_bounded_error():
    completions = FakeCompletions(error=FakeRateLimitError("raw provider rate limit"))

    with pytest.raises(ProviderRateLimitError) as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["retryable"] is True
    assert diagnostic["status_code"] == 429
    assert diagnostic["error_code"] == "openai_rate_limit"
    assert "raw provider rate limit" not in str(diagnostic)


def test_structured_chat_completion_maps_connectivity_to_safe_diagnostic():
    completions = FakeCompletions(error=RuntimeError("raw provider host detail"))

    with pytest.raises(ProviderConnectivityError) as exc_info:
        create_structured_chat_completion(
            chat=FakeChat(completions),
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            schema_name="test_schema",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["error_code"] == "openai_connectivity_error"
    assert diagnostic["status_code"] == 502
    assert diagnostic["details"] == {"exception_class": "RuntimeError"}
    assert "raw provider host detail" not in str(diagnostic)


def test_structured_output_error_name_remains_backward_compatible():
    assert StructuredOutputError is ProviderCallError
    assert issubclass(ProviderRefusalError, ProviderCallError)


def test_proactive_goal_creator_uses_configured_model_instructions_and_schema(monkeypatch):
    completions = FakeCompletions({
        "improved_prompt": "Phase: PLANNING\nImproved prompt",
        "workflow_phase": "PLANNING",
        "preserved_constraints": ["Do not draft a policy"],
    })
    install_fake_openai(monkeypatch, completions)

    role = ProactiveGoalCreator(
        model="gpt-configured",
        instructions="CUSTOM PROACTIVE INSTRUCTIONS",
    )
    result = role.execute("Phase: PLANNING\nInput")

    assert result == "Phase: PLANNING\nImproved prompt"
    call = completions.calls[0]
    assert call["model"] == "gpt-configured"
    assert call["messages"][0] == {
        "role": "system",
        "content": "CUSTOM PROACTIVE INSTRUCTIONS",
    }
    assert call["response_format"]["json_schema"]["name"] == "context_agent_proactive_prompt"
    assert "improved_prompt" in call["response_format"]["json_schema"]["schema"]["required"]


def test_proactive_goal_creator_uses_configured_responses_mode(monkeypatch):
    completions = FakeCompletions({"unexpected": "chat path"})
    responses = FakeResponses({
        "improved_prompt": "Improved via responses",
        "workflow_phase": "PLANNING",
        "preserved_constraints": ["Do not draft a policy"],
    })
    install_fake_openai(monkeypatch, completions, responses)
    monkeypatch.setenv("OPENAI_STRUCTURED_API_MODE", "responses")

    role = ProactiveGoalCreator(
        model="gpt-configured",
        instructions="CUSTOM PROACTIVE INSTRUCTIONS",
    )
    result = role.execute("Phase: PLANNING\nInput")

    assert result == "Improved via responses"
    assert completions.calls == []
    assert responses.calls[0]["text"]["format"]["name"] == "context_agent_proactive_prompt"
    assert responses.calls[0]["store"] is False


def test_response_optimiser_uses_configured_model_instructions_and_schema(monkeypatch):
    completions = FakeCompletions({
        "improved_response": "Structured final context",
        "workflow_phase": "POLICY_HANDOFF",
        "preserved_constraints": ["Preserve facts"],
        "context_tags": ["[context:regulation]GDPR"],
    })
    install_fake_openai(monkeypatch, completions)

    role = PromptResponseOptimiser(
        model="gpt-configured",
        instructions="CUSTOM OPTIMISER INSTRUCTIONS",
    )
    result = role.execute("Original prompt", "Raw response")

    assert result == "Structured final context"
    call = completions.calls[0]
    assert call["model"] == "gpt-configured"
    assert call["messages"][0] == {
        "role": "system",
        "content": "CUSTOM OPTIMISER INSTRUCTIONS",
    }
    assert call["response_format"]["json_schema"]["name"] == "context_agent_optimised_response"
    assert "improved_response" in call["response_format"]["json_schema"]["schema"]["required"]


def test_response_optimiser_uses_configured_responses_mode(monkeypatch):
    completions = FakeCompletions({"unexpected": "chat path"})
    responses = FakeResponses({
        "improved_response": "Optimised via responses",
        "workflow_phase": "POLICY_HANDOFF",
        "preserved_constraints": ["Preserve facts"],
        "context_tags": ["[context:sector]Healthcare"],
    })
    install_fake_openai(monkeypatch, completions, responses)
    monkeypatch.setenv("OPENAI_STRUCTURED_API_MODE", "responses")

    role = PromptResponseOptimiser(
        model="gpt-configured",
        instructions="CUSTOM OPTIMISER INSTRUCTIONS",
    )
    result = role.execute("Original prompt", "Raw response")

    assert result == "Optimised via responses"
    assert completions.calls == []
    assert responses.calls[0]["text"]["format"]["name"] == (
        "context_agent_optimised_response"
    )


def test_openai_agent_run_structured_uses_assistant_instructions_and_requested_schema(monkeypatch):
    from app.agents.openai.agent import OpenAIAgent

    completions = FakeCompletions([
        {
            "improved_prompt": "Improved task prompt",
            "workflow_phase": "EXECUTION",
            "preserved_constraints": ["Do not generate a policy"],
        },
        {
            "task_id": "company_profile",
            "status": "completed",
            "findings": ["Healthcare clinic in Spain."],
            "assumptions": [],
            "missing_details": [],
            "risks": ["Patient data exposure."],
            "policy_implications": ["Access controls must be explicit."],
            "rag_retrieval_hints": {
                "collection_families": ["controls"],
                "jurisdictions": ["Spain"],
                "sectors": ["Healthcare"],
                "methodologies": ["ISO 27001"],
                "query_terms": ["patient records access control"],
            },
        },
    ])
    install_fake_openai(monkeypatch, completions)
    agent = OpenAIAgent(
        name="context-agent",
        instructions="ASSISTANT CONTEXT INSTRUCTIONS",
        model="gpt-configured",
        role_instructions={"proactive_goal_creator": "PROACTIVE INSTRUCTIONS"},
    )

    result = agent.run_structured(
        "Execute the company profile task.",
        schema_name="context_agent_task_result",
        json_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
        context_id="ctx-1",
    )

    assert result["task_id"] == "company_profile"
    proactive_call, structured_call = completions.calls
    assert proactive_call["messages"][0]["content"] == "PROACTIVE INSTRUCTIONS"
    assert structured_call["model"] == "gpt-configured"
    assert structured_call["messages"] == [
        {"role": "system", "content": "ASSISTANT CONTEXT INSTRUCTIONS"},
        {"role": "user", "content": "Improved task prompt"},
    ]
    assert structured_call["response_format"]["json_schema"]["name"] == (
        "context_agent_task_result"
    )


class FakeAssistantRuns:
    def __init__(self, retrieved_runs):
        self.retrieved_runs = list(retrieved_runs)
        self.create_calls = []
        self.retrieve_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id="run-1")

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        if self.retrieved_runs:
            return self.retrieved_runs.pop(0)
        return SimpleNamespace(id="run-1", status="in_progress")


class FakeAssistantMessages:
    def __init__(self):
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)


class FakeAssistantThreads:
    def __init__(self, runs):
        self.runs = runs
        self.messages = FakeAssistantMessages()

    def create(self):
        return SimpleNamespace(id="thread-1")


class FakeAssistantClient:
    def __init__(self, runs, *, timeout_seconds=180.0):
        self.timeout_seconds = timeout_seconds
        self.beta = SimpleNamespace(threads=FakeAssistantThreads(runs))


def install_fake_assistant_agent(monkeypatch, retrieved_runs, *, timeout_seconds=180.0):
    from app.agents.openai import agent as agent_module
    from app.agents.openai.agent import OpenAIAgent

    fake_runs = FakeAssistantRuns(retrieved_runs)
    fake_client = FakeAssistantClient(fake_runs, timeout_seconds=timeout_seconds)
    monkeypatch.setattr(agent_module, "OpenAIClient", lambda: fake_client)

    class FakeProactive:
        def __init__(self, **kwargs):
            pass

        def execute(self, prompt):
            return f"refined: {prompt}"

    monkeypatch.setattr(agent_module, "ProactiveGoalCreator", FakeProactive)
    agent = OpenAIAgent(
        name="context-agent",
        instructions="Assistant instructions",
        model="gpt-configured",
    )
    agent.assistant_id = "assistant-1"
    return agent, fake_client


def test_openai_agent_run_maps_failed_assistant_run_to_safe_diagnostic(monkeypatch):
    failed_run = SimpleNamespace(
        id="run-1",
        status="failed",
        last_error=SimpleNamespace(code="invalid_prompt", message="raw provider text"),
        incomplete_details=None,
    )
    agent, _ = install_fake_assistant_agent(monkeypatch, [failed_run])

    with pytest.raises(ProviderConnectivityError) as exc_info:
        agent.run("user company context")

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["api_mode"] == "assistants"
    assert diagnostic["phase"] == "assistant_run"
    assert diagnostic["details"] == {
        "run_status": "failed",
        "last_error_code": "invalid_prompt",
    }
    assert "raw provider text" not in str(diagnostic)
    assert "user company context" not in str(diagnostic)


def test_openai_agent_run_maps_rate_limited_assistant_run(monkeypatch):
    failed_run = SimpleNamespace(
        id="run-1",
        status="failed",
        last_error=SimpleNamespace(code="rate_limit_exceeded", message="quota details"),
        incomplete_details=None,
    )
    agent, _ = install_fake_assistant_agent(monkeypatch, [failed_run])

    with pytest.raises(ProviderRateLimitError) as exc_info:
        agent.run("user company context")

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["error_code"] == "openai_rate_limit"
    assert diagnostic["details"] == {
        "run_status": "failed",
        "last_error_code": "rate_limit_exceeded",
    }
    assert "quota details" not in str(diagnostic)


def test_openai_agent_run_maps_incomplete_assistant_run(monkeypatch):
    incomplete_run = SimpleNamespace(
        id="run-1",
        status="incomplete",
        last_error=None,
        incomplete_details=SimpleNamespace(reason="max_completion_tokens"),
    )
    agent, _ = install_fake_assistant_agent(monkeypatch, [incomplete_run])

    with pytest.raises(ProviderIncompleteError) as exc_info:
        agent.run("user company context")

    assert exc_info.value.to_diagnostic()["details"] == {
        "run_status": "incomplete",
        "incomplete_reason": "max_completion_tokens",
    }


def test_openai_agent_run_times_out_pending_assistant_run(monkeypatch):
    from app.agents.openai import agent as agent_module

    pending_run = SimpleNamespace(
        id="run-1",
        status="in_progress",
        last_error=None,
        incomplete_details=None,
    )
    agent, _ = install_fake_assistant_agent(
        monkeypatch,
        [pending_run],
        timeout_seconds=1.0,
    )
    monotonic_values = iter([0.0, 1.1])
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(agent_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ProviderTimeoutError) as exc_info:
        agent.run("user company context")

    diagnostic = exc_info.value.to_diagnostic()
    assert diagnostic["api_mode"] == "assistants"
    assert diagnostic["details"] == {"last_status": "in_progress"}


def test_factory_passes_role_instructions_when_backend_accepts_them(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    config = tmp_path / "context_agent.yaml"
    config.write_text(
        """
name: context-agent
type: fake
instructions: Assistant instructions
model: gpt-configured
tools: []
role_instructions:
  proactive_goal_creator: YAML proactive
  response_optimiser: YAML optimiser
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(factory.importlib, "import_module", lambda module_path: None)
    monkeypatch.setitem(AGENT_REGISTRY, "fake", FakeAgent)

    factory.create_agent_from_config(str(config))

    assert captured["instructions"] == "Assistant instructions"
    assert captured["model"] == "gpt-configured"
    assert captured["role_instructions"] == {
        "proactive_goal_creator": "YAML proactive",
        "response_optimiser": "YAML optimiser",
    }
