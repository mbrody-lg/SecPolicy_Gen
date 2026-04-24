# Service Playbooks

This directory contains service-specific workflow guidance for contributors.

Use these playbooks when changing testing, lint-sensitive code, or security-sensitive paths in a service.

## Shared Operating Model

- Start from the smallest useful change and the lowest useful validation layer.
- Use `make lint` from the repository root as the shared lint entrypoint.
- Treat live external tests as opt-in only.
- Prefer host-side tests for deterministic logic and route behavior.
- Use Docker-backed validation when the change depends on runtime wiring, service topology, or container parity.
- Associate each meaningful change with its own commit whenever practical.
- Keep commits scoped to one coherent change set and explain the intent in the commit message, not only the mechanics.
- Split documentation/governance commits from runtime-behavior commits unless the documentation is inseparable from the code change.

## Cross-Service Validation Ladder

Use this ladder when the change crosses service boundaries, changes Docker/runtime configuration, or touches the end-to-end pipeline:

1. `make up`
2. `make policy-tests`
3. `make validator-tests`
4. `make functional-smoke`

Use `make host-fast-tests` before the Docker ladder when the change is still local and deterministic enough to validate on the host. Move to the Docker ladder as soon as service wiring, config resolution, container bootstrap, or real service-to-service calls become part of the risk.

When the work needs a single CI-aligned evidence command for the full critical loop, use `make critical-path-validation`. It runs the service suites for `context-agent`, `policy-agent`, and `validator-agent`, then resets into the Docker smoke run.

### Process Notes From The Current Initiative

- Keep Docker test targets non-interactive so they work in automated terminals without `-it`.
- For `policy-agent`, prefer CPU-only model bootstrap plus local-only model loading when container size and security posture both matter.
- For end-to-end smoke runs, do not assume config paths like `/config/...`; resolve each service's effective `CONFIG_PATH` at runtime before swapping mock configs.
- The smoke and critical-path entrypoints should validate `/health` and `/ready` on the three services and leave one correlation-backed diagnostics lookup for the Context -> Policy -> Validator loop.
- When a route returns a redirect, inspect the structured pipeline result or service logs before assuming the pipeline succeeded.

## Service Playbooks

- [Context Agent](./context-agent.md)
- [Policy Agent](./policy-agent.md)
- [Validator Agent](./validator-agent.md)

## When To Use Them

- Use the service playbook before changing tests, lint-sensitive code, or security-sensitive paths in that service.
- Use the root project documentation when you need the global rule, then return to the service playbook for execution details.
- Update the relevant playbook when a service workflow changes in a non-self-explanatory way.
