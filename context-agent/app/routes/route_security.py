"""Route security classification for Context Agent HTTP boundaries."""

from __future__ import annotations

from dataclasses import dataclass


PUBLIC_READ = "public_read"
OPERATOR_UI_MUTATION = "operator_ui_mutation"
SERVICE_CALLBACK = "service_to_service_callback"
RUNTIME_ENDPOINT = "runtime_endpoint"

INPUT_CONTRACT_GUARD = "input_contract"
BODY_CONTRACT_GUARD = "body_contract"
WORKFLOW_GUARD = "workflow_state_guard"
BOUNDED_OUTPUT_GUARD = "bounded_output"


@dataclass(frozen=True)
class RouteSecurityClassification:
    """Security classification for one Context Agent route method."""

    rule: str
    method: str
    category: str
    current_guard: str
    next_control: str
    rationale: str


MUTATION_BOUNDARY_DECISION = {
    "decision": "inventory_gate_first",
    "reason": (
        "Classify every mutating route before adding CSRF, operator auth, "
        "service-auth, or diagnostics access-control behavior."
    ),
    "next_slice": "service-to-service callback protection or CSRF/operator guard implementation",
}


ROUTE_SECURITY_CLASSIFICATIONS = (
    RouteSecurityClassification(
        rule="/health",
        method="GET",
        category=RUNTIME_ENDPOINT,
        current_guard=BOUNDED_OUTPUT_GUARD,
        next_control="none",
        rationale="Lightweight liveness endpoint; no mutable state.",
    ),
    RouteSecurityClassification(
        rule="/ready",
        method="GET",
        category=RUNTIME_ENDPOINT,
        current_guard=BOUNDED_OUTPUT_GUARD,
        next_control="none",
        rationale="Readiness endpoint returns bounded dependency state.",
    ),
    RouteSecurityClassification(
        rule="/metrics",
        method="GET",
        category=RUNTIME_ENDPOINT,
        current_guard=BOUNDED_OUTPUT_GUARD,
        next_control="deployment_network_boundary",
        rationale="Prometheus metrics endpoint should remain deployment-network scoped.",
    ),
    RouteSecurityClassification(
        rule="/system/status",
        method="GET",
        category=PUBLIC_READ,
        current_guard=BOUNDED_OUTPUT_GUARD,
        next_control="none",
        rationale="Operator status read only; payload is bounded.",
    ),
    RouteSecurityClassification(
        rule="/system/refresh",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=WORKFLOW_GUARD,
        next_control="operator_mutation_guard",
        rationale="Triggers RAG refresh behavior from the operator UI.",
    ),
    RouteSecurityClassification(
        rule="/",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Dashboard read with bounded query parameters.",
    ),
    RouteSecurityClassification(
        rule="/create",
        method="GET",
        category=PUBLIC_READ,
        current_guard=BOUNDED_OUTPUT_GUARD,
        next_control="none",
        rationale="Renders context creation form.",
    ),
    RouteSecurityClassification(
        rule="/create",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Creates a persisted context and may call the provider.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Reads one context and renders bounded stored content.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/security_context",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Returns allowlisted security-context payload.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-plan",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Returns allowlisted context-plan payload.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-building/answers",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Persists context-building answers and updates context state.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-building/questions/defer",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Mutates context-building question state.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/continue",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Persists additional context and may call the provider.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-plan/approve",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Approves the context plan and mutates workflow state.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-plan/execute",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=WORKFLOW_GUARD,
        next_control="operator_mutation_guard",
        rationale="Starts asynchronous context-plan execution.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/final-context/synthesize",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=WORKFLOW_GUARD,
        next_control="operator_mutation_guard",
        rationale="Synthesizes final context and updates workflow state.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/final-context/sections/improve",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Stores final-context review comments and marks sections for improvement.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/final-context/sections/regenerate",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=WORKFLOW_GUARD,
        next_control="operator_mutation_guard",
        rationale="Regenerates marked final-context sections.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-lessons/export",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="operator_read_guard_if_exports_expand",
        rationale="Exports reviewed context lessons through bounded service output.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/context-lessons/<lesson_id>/status",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Mutates lesson review status.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/delete",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Deletes persisted context and interactions.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/policy",
        method="POST",
        category=SERVICE_CALLBACK,
        current_guard=BODY_CONTRACT_GUARD,
        next_control="service_to_service_auth",
        rationale="Internal callback that persists validated policy payloads.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/generate_policy",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=WORKFLOW_GUARD,
        next_control="operator_mutation_guard",
        rationale="Starts asynchronous policy generation and validation.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/system/refresh",
        method="POST",
        category=OPERATOR_UI_MUTATION,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="operator_mutation_guard",
        rationale="Triggers runtime refresh from a context page.",
    ),
    RouteSecurityClassification(
        rule="/pipeline/jobs/<job_id>",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Returns allowlisted job state.",
    ),
    RouteSecurityClassification(
        rule="/pipeline/jobs/<job_id>/events",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Returns allowlisted pipeline events.",
    ),
    RouteSecurityClassification(
        rule="/context/<context_id>/pipeline/jobs/active",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="none",
        rationale="Returns allowlisted active-job state.",
    ),
    RouteSecurityClassification(
        rule="/diagnostics/<correlation_id>",
        method="GET",
        category=PUBLIC_READ,
        current_guard=INPUT_CONTRACT_GUARD,
        next_control="diagnostics_access_control",
        rationale="Diagnostics payload is bounded but access control remains an INIT-11 follow-up.",
    ),
)


def route_security_inventory() -> dict[tuple[str, str], RouteSecurityClassification]:
    """Return route security classifications keyed by method and Flask rule."""
    return {
        (classification.method, classification.rule): classification
        for classification in ROUTE_SECURITY_CLASSIFICATIONS
    }
