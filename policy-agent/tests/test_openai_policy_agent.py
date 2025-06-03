import pytest
from unittest.mock import patch
from app.services.logic import run_with_agent

@patch("app.agents.openai.agent.OpenAIAgent._chat")
def test_openai_policy_agent_pipeline(mock_chat, app_context, default_context_id, openai_model_version):

    mock_chat.return_value = "[OpenAI simulation] generated response"


    refined_prompt = "Create a policy to protect an SME's digital assets according to ISO 27001 and GDPR."

    result = run_with_agent(
        refined_prompt=refined_prompt,
        context_id=default_context_id,
        model_version=openai_model_version
    )

    assert isinstance(result, dict)
    assert "text" in result
    assert "structured_plan" in result
    assert "context_id" in result
    assert result["context_id"] == default_context_id
    assert "[OpenAI simulation] generated response" in result["text"]
    assert isinstance(result["structured_plan"], list)
    assert mock_chat.call_count >= 1  # ha de cridar almenys una vegada