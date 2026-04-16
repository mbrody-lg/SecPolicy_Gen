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
- Record strategy or policy changes in `.local-workspace/decision-log/`.
- If a validation step cannot run, record the blocker in `.local-workspace/proposed-actions/BACKLOG.md`.

## Service Playbooks

- [Context Agent](./context-agent.md)
- [Policy Agent](./policy-agent.md)
- [Validator Agent](./validator-agent.md)

## When To Use Them

- Use the service playbook before changing tests, lint-sensitive code, or security-sensitive paths in that service.
- Use the root project documentation when you need the global rule, then return to the service playbook for execution details.
- Update the relevant playbook when a service workflow changes in a non-self-explanatory way.
