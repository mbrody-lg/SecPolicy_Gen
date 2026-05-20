from copy import deepcopy

from bson import ObjectId


def base_security_context():
    return {
        "profile": {
            "sector": "Healthcare",
            "operating_countries": ["Spain"],
            "region": "EU",
        },
        "information_assets": {
            "critical_assets": ["Patient records"],
            "data_categories": ["health_data"],
            "third_party_dependencies": ["Laboratory provider"],
        },
        "compliance": {
            "jurisdictions": ["Spain", "EU"],
            "regulatory_hints": ["GDPR"],
            "methodologies": ["ISO 27001"],
        },
        "analysis": {
            "missing_information": [],
            "confidence": "medium",
        },
        "retrieval_hints": {
            "collection_families": ["legal_norms", "security_controls"],
        },
    }


def approved_plan():
    return {
        "version": "1.0",
        "status": "approved",
        "approved_revision_id": "plan-rev-1",
        "review": {
            "required": False,
            "approved_at": "2026-05-20T10:00:00+00:00",
            "approval_source": "user",
            "user_feedback": "Approved for dental clinic scope.",
            "context_snapshot_hash": "hash-1",
        },
        "tasks": [
            {
                "id": "information_assets",
                "order": 1,
                "title": "Information assets",
                "objective": "Identify critical information assets.",
                "expected_output": "Asset list and ownership assumptions.",
                "dependencies": [],
                "status": "approved",
            }
        ],
    }


def completed_task_results():
    return {
        "version": "1.0",
        "status": "completed",
        "plan_revision_id": "plan-rev-1",
        "context_snapshot_hash": "hash-1",
        "tasks": [
            {
                "task_id": "information_assets",
                "title": "Information assets",
                "status": "completed",
                "result": "## Information assets\nPatient records are the primary asset.\n\n- Owner: clinic manager\n- Storage: cloud EHR",
            }
        ],
    }


def final_context(status="ready"):
    context_ready = status == "ready"
    return {
        "version": "1.0",
        "status": status,
        "context_ready_for_policy": context_ready,
        "sections": {
            "task_findings": {
                "status": "accepted" if context_ready else "needs_improvement",
                "content": "## Information assets\nPatient records are the primary asset.",
                "items": [
                    {
                        "item_id": "information_assets",
                        "order": 1,
                        "title": "Information assets",
                        "status": "completed",
                        "content": "## Information assets\nPatient records are the primary asset.\n\n- Owner: clinic manager\n- Storage: cloud EHR",
                    }
                ],
                "comments": [] if context_ready else [
                    {"comment": "Expand system ownership.", "created_at": "2026-05-20T10:30:00+00:00"}
                ],
            }
        },
    }


def context_document(context_id, state):
    doc = {
        "_id": ObjectId(context_id),
        "country": "Spain",
        "sector": "Healthcare",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
        "status": "created",
        "security_context": base_security_context(),
    }
    if state == "intake":
        return doc
    if state == "questions":
        doc.update({
            "status": "context_building_needs_information",
            "context_building": {
                "version": "1.0",
                "status": "needs_information",
                "missing_information": ["third_party_dependencies"],
                "questions": [
                    {
                        "id": "q1",
                        "status": "pending",
                        "question": "Which third-party providers process patient records?",
                        "rationale": "Vendor scope affects policy controls.",
                    }
                ],
            },
        })
        return doc
    if state == "planning":
        doc.update({
            "status": "context_plan_ready_for_review",
            "context_building": {"version": "1.0", "status": "sufficient", "questions": []},
            "context_intelligence_plan": {
                **approved_plan(),
                "status": "draft",
                "approved_revision_id": None,
                "review": {"required": True},
            },
        })
        return doc
    if state == "executed":
        doc.update({
            "status": "context_plan_executed",
            "context_building": {"version": "1.0", "status": "sufficient", "questions": []},
            "context_intelligence_plan": approved_plan(),
            "context_task_results": completed_task_results(),
        })
        return doc
    if state == "final_needs_improvement":
        doc.update({
            "status": "final_context_needs_improvement",
            "context_building": {"version": "1.0", "status": "sufficient", "questions": []},
            "context_intelligence_plan": approved_plan(),
            "context_task_results": completed_task_results(),
            "final_context": final_context("needs_improvement"),
            "refined_prompt": "Final company security context.",
        })
        return doc
    if state == "final_only":
        doc.update({
            "status": "context_ready_for_policy",
            "context_building": {"version": "1.0", "status": "sufficient", "questions": []},
            "context_intelligence_plan": approved_plan(),
            "final_context": final_context("ready"),
            "refined_prompt": "Final company security context.",
        })
        return doc
    if state == "ready":
        doc.update({
            "status": "context_ready_for_policy",
            "context_building": {"version": "1.0", "status": "sufficient", "questions": []},
            "context_intelligence_plan": approved_plan(),
            "context_task_results": completed_task_results(),
            "final_context": final_context("ready"),
            "refined_prompt": "Final company security context.",
        })
        return doc
    raise ValueError(f"Unknown UI workflow fixture state: {state}")


def interactions(context_id):
    return [
        {
            "context_id": ObjectId(context_id),
            "origin": "user",
            "answer": "We operate a dental clinic with patient records.",
            "timestamp": 1,
        },
        {
            "context_id": ObjectId(context_id),
            "origin": "agent",
            "answer": "## Context Agent assessment\nThe initial context is sufficient for planning.",
            "timestamp": 2,
        },
    ]
