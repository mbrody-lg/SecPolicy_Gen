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
