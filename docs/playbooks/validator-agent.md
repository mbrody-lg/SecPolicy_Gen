# Validator Agent Playbook

This playbook is the service-specific execution guide for `validator-agent`.

Use this playbook when changing validator routes, service helpers, coordinator behavior, or the validation workflow.

## Testing Workflow

- Start with the smallest test that proves the change.
- Prefer targeted `pytest` runs against the affected module or test file before widening the scope.
- Use `validator-agent/tests/test_services_logic.py` for outbound policy-agent update behavior.
- Use `validator-agent/tests/test_routes.py` for HTTP contract and request-validation changes.
- Use `validator-agent/tests/test_integration_validate_policy.py` for broader request-to-response coverage.
- Keep `validator-agent/tests/test_mistral_real.py` out of the default loop; it is a live external test and should remain opt-in.
- Use `make validator-tests` when you need container parity or when local execution is blocked by Flask, Mongo, or service bootstrap differences.
- If a failure depends on the service runtime, bring the stack up with `make up`, reproduce the issue, then shut it down with `make down` when you are done.

## Pylint Workflow

- Treat `pyproject.toml` at the repo root as the lint source of truth.
- Run `make lint` to check the active baseline for `validator-agent/app`.
- Fix behavior first, then adjust lint shape if the code still needs cleanup.
- Keep lint changes focused on real defects or maintainability issues in production code.
- Do not widen lint scope to tests or scripts unless the change is explicitly about lint policy.

## Security-Control Workflow

- Treat request validation, ObjectId parsing, secret handling, and outbound calls to `policy-agent` as security-sensitive boundaries.
- Review `validator-agent/app/routes/routes.py` and `validator-agent/app/services/logic.py` first when the change affects input handling or cross-service communication.
- Test malformed input, missing required fields, invalid context IDs, and request-failure paths.
- Keep the `DELETE /validation/<context_id>` guard tied to testing mode only.
- Do not make live external calls part of the default validation path.
- Use regression tests for security-relevant fixes when practical, especially for failure handling and boundary validation.

## Practical Decision Rules

- If the change is route-level, stay in route tests until the behavior is clear.
- If the change is service orchestration, isolate it with mocks before moving to Docker-backed validation.
- If the change touches external dependencies or live model calls, separate the opt-in path from the default suite.
- If the change affects lint or security policy, keep the code change small and document the follow-up work in the normal governance flow.

## Commit Discipline

- Prefer one commit per coherent `validator-agent` change.
- Make the commit message explain whether the change affects validation routing, coordinator flow, policy-agent update contracts, or contributor workflow.
- Keep runtime contract changes separate from documentation/playbook updates whenever practical.
