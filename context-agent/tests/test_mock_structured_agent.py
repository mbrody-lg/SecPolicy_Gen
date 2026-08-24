from app.agents.mock.agent import MockAgent


def test_mock_task_result_is_compact_and_structured():
    agent = MockAgent(
        name="Mock Context Agent",
        instructions="Return deterministic output.",
        model="simulator-llm",
    )
    prompt = "Sensitive context " * 10_000

    result = agent.run_structured(
        prompt,
        schema_name="context_agent_task_result",
        json_schema={},
        context_id="507f1f77bcf86cd799439011",
    )

    assert result["status"] == "completed"
    assert result["rag_retrieval_hints"]["collection_families"] == ["controls"]
    assert len(str(result)) < 2_000
    assert "Sensitive context" not in str(result)
