# Observability Log Contract

This contract applies to structured JSON log events emitted by `context-agent`, `policy-agent`, and `validator-agent`.

## Required Fields

Every structured event must include:

- `event`: stable dotted event name.
- `service`: emitting service name.
- `stage`: bounded lifecycle stage.
- `result`: bounded lifecycle result such as `started`, `success`, `failure`, `skipped`, or `unknown`.

## Optional Fields

Use these fields consistently when the data is available and safe:

- `correlation_id`: trace metadata only, not an authentication or authorization signal.
- `context_id`: business context identifier.
- `route`: HTTP route pattern.
- `method`: HTTP method.
- `status_code`: HTTP or dependency response code.
- `error_code`: stable internal error code.

Numeric timing fields such as `duration_ms` and `timeout_seconds` should remain numeric values, not formatted strings.

## Safety Rules

Structured logs must not include prompts, policy bodies, retrieved chunks, provider payloads, secrets, raw exception text, config paths, dependency hosts, internal URLs, or unbounded response bodies.

Use diagnostics documents for bounded cross-service evidence and keep log events as compact stage markers.
