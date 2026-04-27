from unittest.mock import patch
from app.services.logic import run_with_agent, update_with_agent


@patch("app.agents.openai.agent.RAGProcessor")
@patch("app.agents.openai.agent.OpenAIAgent._chat")
def test_openai_policy_agent_pipeline(
    mock_chat,
    mock_rag_processor,
    app_context,
    default_context_id,
    openai_model_version,
):
    mock_rag_processor.return_value.apply.return_value = "[RAG] enriched prompt"
    mock_chat.side_effect = [
        "proposal alpha",
        "proposal beta",
        "proposal gamma",
        "combined proposal",
        "final policy",
    ]

    refined_prompt = (
        "Create a policy to protect an SME's digital assets according to ISO 27001 and GDPR."
    )

    result = run_with_agent(
        refined_prompt=refined_prompt,
        context_id=default_context_id,
        model_version=openai_model_version,
    )

    assert isinstance(result, dict)
    assert "text" in result
    assert "structured_plan" in result
    assert "context_id" in result
    assert result["context_id"] == default_context_id
    assert result["text"] == "final policy"
    assert isinstance(result["structured_plan"], list)
    assert len(result["structured_plan"]) == 3
    retrieval_plan = mock_rag_processor.return_value.apply.call_args.kwargs["retrieval_plan"]
    assert retrieval_plan.context_id == default_context_id
    assert "legal_norms" in retrieval_plan.required_families
    assert mock_chat.call_count == 5
    assert mock_chat.call_args_list[0].args[0] == "[RAG] enriched prompt"
    assert mock_chat.call_args_list[1].args[0] == "[RAG] enriched prompt"
    assert mock_chat.call_args_list[2].args[0] == "[RAG] enriched prompt"
    assert (
        mock_chat.call_args_list[3].args[0]
        == "Proposal proposal_1:\nproposal alpha\n\n"
        "Proposal proposal_2:\nproposal beta\n\n"
        "Proposal proposal_3:\nproposal gamma"
    )
    assert mock_chat.call_args_list[4].args[0] == "combined proposal"


@patch("app.agents.openai.agent.OpenAIAgent._chat")
def test_openai_policy_agent_update_uses_single_model_call(
    mock_chat,
    app_context,
    default_context_id,
    openai_model_version,
):
    mock_chat.return_value = "updated policy"

    result = update_with_agent(
        prompt="Refine this policy draft",
        context_id=default_context_id,
        model_version=openai_model_version,
    )

    assert result["text"] == "updated policy"
    assert mock_chat.call_count == 1
    assert mock_chat.call_args_list[0].args[0] == "Refine this policy draft"


@patch("app.agents.openai.agent.RAGProcessor")
@patch("app.agents.openai.agent.OpenAIAgent._chat")
def test_run_with_agent_builds_contextual_retrieval_plan(
    mock_chat,
    mock_rag_processor,
    app_context,
    default_context_id,
    openai_model_version,
):
    mock_rag_processor.return_value.apply.return_value = "[RAG] healthcare prompt"
    mock_chat.side_effect = [
        "proposal alpha",
        "proposal beta",
        "proposal gamma",
        "combined proposal",
        "final policy",
    ]

    run_with_agent(
        refined_prompt="Protect patient data under GDPR.",
        context_id=default_context_id,
        model_version=openai_model_version,
        business_context={
            "language": "en",
            "country": "Spain",
            "sector": "Private healthcare",
            "critical_assets": ["Medical data"],
            "methodology": "ISO 27799",
            "need": "Protect patient data",
        },
    )

    retrieval_plan = mock_rag_processor.return_value.apply.call_args.kwargs["retrieval_plan"]
    assert retrieval_plan.context_id == default_context_id
    assert retrieval_plan.required_families == [
        "legal_norms",
        "implementation_guides",
        "sector_norms",
        "security_frameworks",
        "risk_methodologies",
    ]
    assert {step.collection for step in retrieval_plan.steps} == {
        "normativa",
        "guia",
        "sector",
        "metodologia",
    }
