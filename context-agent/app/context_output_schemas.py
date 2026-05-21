"""JSON Schemas for Context Agent structured phase outputs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


STRING_ARRAY = {
    "type": "array",
    "items": {"type": "string"},
}

RETRIEVAL_HINTS_SCHEMA = {
    "type": "object",
    "properties": {
        "collection_families": STRING_ARRAY,
        "jurisdictions": STRING_ARRAY,
        "sectors": STRING_ARRAY,
        "methodologies": STRING_ARRAY,
        "query_terms": STRING_ARRAY,
    },
    "required": [
        "collection_families",
        "jurisdictions",
        "sectors",
        "methodologies",
        "query_terms",
    ],
    "additionalProperties": False,
}

CONTEXT_BUILDING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "explicit_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_path": {"type": "string"},
                    "value": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["field_path", "value", "source"],
                "additionalProperties": False,
            },
        },
        "assumptions": STRING_ARRAY,
        "missing_information": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_path": {"type": "string"},
                    "question": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["field_path", "question", "rationale"],
                "additionalProperties": False,
            },
        },
        "follow_up_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "answer_field": {"type": "string"},
                    "question": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["id", "answer_field", "question", "rationale"],
                "additionalProperties": False,
            },
        },
        "security_domains": STRING_ARRAY,
        "rag_retrieval_hints": RETRIEVAL_HINTS_SCHEMA,
        "next_action": {"type": "string"},
    },
    "required": [
        "summary",
        "explicit_facts",
        "assumptions",
        "missing_information",
        "follow_up_questions",
        "security_domains",
        "rag_retrieval_hints",
        "next_action",
    ],
    "additionalProperties": False,
}

CONTEXT_PLANNING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_summary": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "order": {"type": "integer"},
                    "title": {"type": "string"},
                    "objective": {"type": "string"},
                    "dependencies": STRING_ARRAY,
                    "expected_output": {"type": "string"},
                },
                "required": [
                    "id",
                    "order",
                    "title",
                    "objective",
                    "dependencies",
                    "expected_output",
                ],
                "additionalProperties": False,
            },
        },
        "missing_context_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "answer_field": {"type": "string"},
                    "question": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["answer_field", "question", "rationale"],
                "additionalProperties": False,
            },
        },
        "approval_recommendation": {"type": "string"},
    },
    "required": [
        "plan_summary",
        "tasks",
        "missing_context_questions",
        "approval_recommendation",
    ],
    "additionalProperties": False,
}

CONTEXT_TASK_RESULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "status": {"type": "string", "enum": ["completed", "needs_more_context", "failed"]},
        "findings": STRING_ARRAY,
        "assumptions": STRING_ARRAY,
        "missing_details": STRING_ARRAY,
        "risks": STRING_ARRAY,
        "policy_implications": STRING_ARRAY,
        "rag_retrieval_hints": RETRIEVAL_HINTS_SCHEMA,
    },
    "required": [
        "task_id",
        "status",
        "findings",
        "assumptions",
        "missing_details",
        "risks",
        "policy_implications",
        "rag_retrieval_hints",
    ],
    "additionalProperties": False,
}

FINAL_CONTEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "status": {"type": "string", "enum": ["accepted", "needs_improvement"]},
                },
                "required": ["section_id", "title", "content", "status"],
                "additionalProperties": False,
            },
        },
        "assumptions": STRING_ARRAY,
        "unresolved_gaps": STRING_ARRAY,
        "rag_retrieval_hints": RETRIEVAL_HINTS_SCHEMA,
        "policy_handoff": {
            "type": "object",
            "properties": {
                "business_context": {"type": "string"},
                "regulatory_context": {"type": "string"},
                "asset_data_exposure": {"type": "string"},
                "risk_tolerance": {"type": "string"},
                "policy_objective": {"type": "string"},
            },
            "required": [
                "business_context",
                "regulatory_context",
                "asset_data_exposure",
                "risk_tolerance",
                "policy_objective",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "summary",
        "sections",
        "assumptions",
        "unresolved_gaps",
        "rag_retrieval_hints",
        "policy_handoff",
    ],
    "additionalProperties": False,
}

CONTEXT_PHASE_OUTPUT_SCHEMAS = {
    "context_building": CONTEXT_BUILDING_OUTPUT_SCHEMA,
    "context_planning": CONTEXT_PLANNING_OUTPUT_SCHEMA,
    "context_task_result": CONTEXT_TASK_RESULT_OUTPUT_SCHEMA,
    "final_context": FINAL_CONTEXT_OUTPUT_SCHEMA,
}


def context_phase_output_schema(name: str) -> dict[str, Any]:
    """Return a defensive copy of a Context Agent phase output schema."""
    try:
        return deepcopy(CONTEXT_PHASE_OUTPUT_SCHEMAS[name])
    except KeyError as error:
        raise ValueError(f"Unknown Context Agent output schema: {name}") from error
