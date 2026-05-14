"""Prometheus metrics helpers for context-agent."""

from time import perf_counter

from flask import Response, g, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

SERVICE_NAME = "context-agent"

REQUEST_COUNT = Counter(
    "secpolicy_http_requests_total",
    "HTTP requests handled by SecPolicyGen services.",
    ["service", "method", "route", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "secpolicy_http_request_duration_seconds",
    "HTTP request latency for SecPolicyGen services.",
    ["service", "method", "route"],
)
PIPELINE_JOB_TRANSITIONS = Counter(
    "secpolicy_pipeline_job_transitions_total",
    "Pipeline job state transitions observed by context-agent.",
    ["status", "stage"],
)
PIPELINE_JOB_TERMINALS = Counter(
    "secpolicy_pipeline_job_terminals_total",
    "Terminal pipeline job outcomes observed by context-agent.",
    ["status", "stage", "error_code"],
)
PIPELINE_JOB_DURATION = Histogram(
    "secpolicy_pipeline_job_duration_seconds",
    "Pipeline job duration from creation/start to terminal state.",
    ["status"],
)


def start_request_timer() -> None:
    """Store request start time for latency metrics."""
    g.metrics_started_at = perf_counter()


def record_request_metrics(response) -> None:
    """Record bounded request metrics without logging request payloads."""
    if request.path == "/metrics":
        return
    route = request.url_rule.rule if request.url_rule else request.path
    method = request.method
    REQUEST_COUNT.labels(SERVICE_NAME, method, route, str(response.status_code)).inc()
    started_at = getattr(g, "metrics_started_at", None)
    if started_at is not None:
        REQUEST_LATENCY.labels(SERVICE_NAME, method, route).observe(perf_counter() - started_at)


def metrics_response() -> Response:
    """Return Prometheus exposition payload."""
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def record_pipeline_job_transition(
    *,
    status: str,
    stage: str,
    error_code: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Record bounded pipeline job metrics without job or context identifiers."""
    PIPELINE_JOB_TRANSITIONS.labels(status=status, stage=stage).inc()
    if status in {"completed", "failed", "cancelled"}:
        PIPELINE_JOB_TERMINALS.labels(
            status=status,
            stage=stage,
            error_code=error_code or "none",
        ).inc()
        if duration_seconds is not None:
            PIPELINE_JOB_DURATION.labels(status=status).observe(max(duration_seconds, 0.0))
