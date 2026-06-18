import pytest

from app.context_output_schemas import (
    CONTEXT_PHASE_OUTPUT_SCHEMAS,
    context_phase_output_schema,
)


def _walk_object_schemas(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _walk_object_schemas(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _walk_object_schemas(item)


def test_context_phase_output_schemas_are_strict_openai_json_schemas():
    expected_names = {
        "context_building",
        "context_planning",
        "context_task_result",
        "final_context",
    }

    assert set(CONTEXT_PHASE_OUTPUT_SCHEMAS) == expected_names
    for schema in CONTEXT_PHASE_OUTPUT_SCHEMAS.values():
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for object_schema in _walk_object_schemas(schema):
            assert object_schema["additionalProperties"] is False
            assert set(object_schema["required"]) == set(object_schema["properties"])


def test_context_phase_output_schema_returns_defensive_copy():
    schema = context_phase_output_schema("context_building")
    schema["properties"]["summary"]["type"] = "integer"

    fresh_schema = context_phase_output_schema("context_building")

    assert fresh_schema["properties"]["summary"]["type"] == "string"


def test_context_phase_output_schema_rejects_unknown_schema():
    with pytest.raises(ValueError, match="Unknown Context Agent output schema"):
        context_phase_output_schema("unknown")


def test_context_building_schema_covers_questions_and_rag_hints():
    schema = context_phase_output_schema("context_building")

    assert "follow_up_questions" in schema["properties"]
    assert "rag_retrieval_hints" in schema["properties"]
    question_schema = schema["properties"]["follow_up_questions"]["items"]
    assert set(question_schema["properties"]) == {
        "id",
        "answer_field",
        "question",
        "rationale",
    }


def test_final_context_schema_covers_policy_handoff_fields():
    schema = context_phase_output_schema("final_context")
    handoff = schema["properties"]["policy_handoff"]

    assert set(handoff["properties"]) == {
        "business_context",
        "regulatory_context",
        "asset_data_exposure",
        "risk_tolerance",
        "policy_objective",
    }


def test_final_context_schema_is_not_policy_agent_handoff_contract():
    schema = context_phase_output_schema("final_context")

    assert "policy_handoff" in schema["properties"]
    assert "structured_findings" not in schema["properties"]["policy_handoff"]["properties"]
