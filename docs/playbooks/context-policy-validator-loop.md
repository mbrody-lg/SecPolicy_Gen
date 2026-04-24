# Context -> Policy -> Validator Operational Runbook

This runbook is the single operational guide for the critical loop that starts in `context-agent`, calls `policy-agent`, and completes in `validator-agent`.

Use it when you need to confirm stack readiness, trace one request across services, collect smoke evidence, or triage a failed end-to-end run.

## Service Map

| Service | Host URL | Core loop role | Health endpoints |
|---------|----------|----------------|------------------|
| Context Agent | `http://localhost:5003` | Starts the loop and stores pipeline diagnostics | `GET /health`, `GET /ready` |
| Policy Agent | `http://localhost:5002` | Generates or revises policy text | `GET /health`, `GET /ready` |
| Validator Agent | `http://localhost:5001` | Validates policy and returns decision data | `GET /health`, `GET /ready` |

`/health` is liveness only. `/ready` is the operational gate: it checks minimal config and dependency availability and is also what Docker Compose uses for each service `healthcheck`.

## Readiness Checks

Start the stack:

```bash
make up
```

Check readiness before running the loop:

```bash
curl -fsS http://localhost:5003/ready
curl -fsS http://localhost:5002/ready
curl -fsS http://localhost:5001/ready
```

Expected behavior:
- `200` means the service is ready for traffic.
- `503` means bootstrap is incomplete or a required dependency/config is unavailable.
- If Docker says a container is unhealthy, inspect `/ready` first, not `/health`.

## Correlation And Structured Logs

The loop uses `X-Correlation-ID` as the shared trace key:
- an inbound `X-Correlation-ID` is preserved when present
- a new correlation id is generated when absent
- the correlation id is returned on HTTP responses
- JSON error payloads keep `correlation_id` aligned with the response header
- cross-service calls reuse that same value

All three agents emit compact JSON log lines with stable keys such as `event`, `service`, `stage`, `correlation_id`, and `context_id`.

Use that combination to follow one request across services:

```bash
make logs
```

Then filter for the correlation id or context id you are chasing.

## Diagnostics Lookup

`context-agent` keeps the bounded pipeline diagnostic view keyed by correlation id.

Lookup endpoint:

```text
GET /diagnostics/<correlation_id>
```

Example:

```bash
curl -fsS http://localhost:5003/diagnostics/<correlation-id>
```

What to expect from the diagnostic document:
- top-level `status`, `context_id`, `correlation_id`, timestamps, and `last_error`
- a bounded `hops` list showing stage-by-stage progress through the loop
- failure metadata such as `error_type`, `error_code`, target service, and status code when available

Use diagnostics when logs are noisy, the UI only shows a flash message, or you need the latest cross-service failure summary for one loop execution.

## Smoke Evidence

For one-command evidence of the critical loop, run:

```bash
make critical-path-validation
```

This runs `context-tests`, `policy-tests`, `validator-tests`, then resets into the Docker smoke sequence.

For the smoke step alone:

```bash
make functional-smoke
```

Evidence artifact:
- `migration/functional-smoke-result.json`

The smoke report records:
- `smoke_timestamp`
- `total_contexts`
- `service_checks`
- `preflight_failures`
- `failed_contexts`
- per-context summary with `generate_status`, `validated_policy_records`, `policy_records`, `validation_rounds`, `last_status`, `failure_reasons`, and `observability`

Treat that JSON file as the default attachable evidence for I9-T4.5 and for any change that affects the end-to-end loop.

## Failure Triage

Follow this order to keep triage short and repeatable:

1. Check `make up` completed and all three `/ready` endpoints return `200`.
2. Re-run `make functional-smoke` or `make critical-path-validation` to get fresh evidence in `migration/functional-smoke-result.json`.
3. Read `preflight_failures` first; then read `failed_contexts` and per-context `failure_reasons` to see whether the failure is readiness, generation, validation, persistence, or diagnostics related.
4. Pull the request `correlation_id` from the failing response, JSON body, or structured logs.
5. Query `http://localhost:5003/diagnostics/<correlation_id>` to confirm the last failed hop and `last_error`.
6. Use `make logs` and filter by that `correlation_id` across the three services.

Common first interpretations:
- `/health` ok but `/ready` fails: config or dependency readiness issue, not an application liveness issue.
- `generate_status` not `200` or `302`: `context-agent` could not complete the policy-generation handoff.
- `missing_policy_record`: `policy-agent` did not persist the expected policy output.
- `missing_validated_policy`: the loop did not persist the validated result back into `context-agent`.
- diagnostics `last_error.stage=validation`: start with `validator-agent` logs and then confirm the upstream callback path into `context-agent`.

## Operator Notes

- Prefer `make critical-path-validation` when you need CI-aligned evidence for the whole loop.
- Prefer `/ready` over ad hoc container inspection when deciding if traffic should proceed.
- Prefer the diagnostics endpoint over manual Mongo inspection for first-pass failure lookup.
- Keep documentation for service-specific testing and security workflows in the per-service playbooks; keep end-to-end loop operations here.
