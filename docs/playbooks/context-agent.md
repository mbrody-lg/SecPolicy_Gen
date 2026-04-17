# Context Agent Playbook

This playbook is the service-specific execution guide for `context-agent`.

## Testing Workflow

- Default service test entrypoint: `make context-tests`.
- The service test suite is rooted at `context-agent/tests` and is configured by `context-agent/pyproject.toml`.
- Prefer unit and route tests with the existing Flask test client fixture in `context-agent/tests/conftest.py`.
- Use mocks or fakes for MongoDB, OpenAI, and other external dependencies unless a test is explicitly validating the integration boundary.
- If local dependency bootstrap is being worked on, follow the root bootstrap policy first, then return to the service suite.
- Add regression coverage for malformed input, persistence failures, and external dependency failures when those paths are changed.
- Keep live tests out of the default path. If a live dependency test is necessary, make it opt-in and isolate it from the normal suite.

## Pylint Workflow

- Run lint from the repository root with `make lint`.
- Treat lint work as a focused session: fix one rule family or one behavior issue set at a time.
- Separate correctness fixes from style cleanup so each change stays reviewable.
- Avoid broad refactors that mix imports, naming, complexity, and docstrings in the same pass.
- If lint config or policy changes are needed, record the decision in the local decision log before considering the update complete.

## Security Control Workflow

- Review every change for untrusted input handling, secret handling, error handling, and failure paths.
- Treat OpenAI and MongoDB interactions as security-sensitive boundaries.
- Do not log secrets or dump full environment values in errors, tests, or debug output.
- Add tests for validation failures and dependency failures when a change touches those paths.
- Use mocked dependencies for routine verification; reserve live security checks for explicit, opt-in validation.
- If a security validation step cannot run, capture the blocker in the backlog rather than skipping it silently.

## Practical Checks

- If a change only touches templates or presentation, still run the relevant route or service tests.
- If a change touches agent logic, check the prompt-generation path and the persistence path together.
- If a change affects external calls, verify both the success path and the fallback or failure path.

## Commit Discipline

- Prefer one commit per coherent `context-agent` change.
- Explain whether the change affects prompt generation, persistence, routing, or contributor workflow.
- Keep documentation-only updates in a separate commit from runtime behavior changes when practical.
