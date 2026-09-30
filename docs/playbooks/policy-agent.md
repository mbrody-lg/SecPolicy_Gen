# Policy Agent Playbook

This playbook is the service-specific execution guide for `policy-agent`.

## Service shape
- Flask service with MongoDB persistence and Chroma-backed retrieval paths.
- Keep route handlers thin and push orchestration into testable service logic.
- Treat external dependencies as boundaries: mock them in fast tests, exercise them in Docker-backed checks when fidelity matters.

## Tenant-Bound Policy Persistence
- Authoritative policy records use `organization_id`, copied only from the
  verified workload principal's tenant. A request body, `X-Tenant-ID`, context
  ID, or correlation ID is not a tenant authority.
- Every policy lookup and mutation must include `organization_id` as well as
  the exact context and policy/revision identity. Return the same bounded 404
  for an absent record and a record owned by another tenant; do not call the
  model or write before this check. A missing owner is not a match.
- A signed tenant claim does not prove ownership of a supplied context ID.
  Context must first verify the context against its own tenant-owned record
  and bind that ID into a signed handoff; Policy must compare it before
  generation. The v2 workload token enforces this binding. The active-revision
  migration remains separate from this context-ownership gate.
- Legacy policy rows without `organization_id` remain inaccessible. Before any
  backfill, inventory and back up them, dry-run a join to Context's
  authoritative `contexts._id`/`organization_id`, and quarantine missing,
  ambiguous, or conflicting matches. Never assign old rows from a request
  tenant or use a context-ID-only fallback. A partial unique tenant/context
  index covers newly generated rows marked `generation_guard`; historical rows
  remain outside that constraint and duplicate legacy rows fail closed on update.
  Do not claim a unique current-policy revision until historical duplicates and
  revision semantics are resolved.
- Candidate generation is non-authoritative and must not mutate policy rows
  or globally shared policy configuration. Any future tenant-scoped provider
  configuration and spending records need their own authorization gate.

## Testing Workflow
1. Start with the smallest useful host-side test scope.
2. Use small fixtures and mock only external boundaries.
3. Prefer route and unit coverage for deterministic behavior.
4. Use Docker-backed validation when the change depends on container wiring, persistence, or Chroma parity.
5. Run the service suite with `make policy-tests`.
6. If the stack is not already up, bring it up before running the containerized test target.
7. Keep regression tests for any security-relevant or externally visible failure path.

### Practical testing rules
- Use host tests for business logic, request validation, and deterministic Flask behavior.
- Use Docker for integration-sensitive paths and anything that depends on runtime parity.
- Do not hide behavior behind oversized fixtures.
- Keep test data small and explicit.

## Pylint Workflow
1. Run `make lint` from the repository root.
2. Fix the highest-signal issues first, starting with correctness and clarity.
3. Keep changes narrow and behavior-preserving unless the lint issue exposes a real bug.
4. Do not lower the baseline or add broad disables to make the score pass.
5. Re-run lint after the code change before widening the scope.

### Practical lint rules
- Prefer small refactors over churny rewrites.
- Keep warnings localized to the touched area when possible.
- If a lint rule needs a strategic exception, document the rationale in the decision log.

## Security-Control Workflow
1. Treat security checks as part of normal implementation work, not a late-stage add-on.
2. Review any change that affects untrusted input, secrets, logging, external calls, or error handling.
3. Keep secrets in configuration and environment management, never in code or examples.
4. Add or update regression tests for security-relevant fixes.
5. Use host tests for validation and failure handling; use Docker-backed checks when the security behavior depends on runtime wiring or containerized services.

### Security checklist
- Is input validated before use?
- Are secrets and sensitive values kept out of logs and responses?
- Does the change increase attack surface through external calls or broader persistence access?
- Is the failure path covered, not only the success path?
- Keep request-body limits explicit for prompt text and validator feedback payloads so cross-service calls stay bounded.
- Keep model downloads explicit for vector workflows; prefer preloading and local-only model use over runtime hub fetches.
- Prefer safetensors-backed model loading and avoid enabling remote model code unless it has been explicitly reviewed.

## Commit Discipline

- Prefer one commit per coherent `policy-agent` change.
- Make the commit message explain whether the change is about bootstrap/configuration, policy-generation flow, persistence ownership, or workflow documentation.
- Keep documentation/playbook edits separate from runtime contract changes unless both must land together to remain understandable.
