# CI Handoff Contract For Docker Gates

Use this contract when preparing INIT-04 GitHub Actions work that will consume
the local Docker validation path established by INIT-01.

This document is a handoff only. It does not implement CI workflows, change
Makefile targets, or modify Compose behavior.

## Stable Local Entrypoints

| Purpose | Command | CI expectation |
|---------|---------|----------------|
| Local dependency bootstrap | `make bootstrap-test-env` | Optional for CI images, useful for parity checks |
| Lint | `make lint` | Required once CI has Python dependencies installed |
| Fast host tests | `make host-fast-tests` | First test gate for deterministic route and service logic |
| Start Docker stack | `make up` | Required before Docker-backed service and smoke gates |
| Context service tests | `make context-tests` | Docker-backed service suite |
| Policy service tests | `make policy-tests` | Docker-backed service suite |
| Policy RAG runtime validation | `make policy-rag-validate` | Lightweight manifest/source/Chroma heartbeat gate without indexing |
| Validator service tests | `make validator-tests` | Docker-backed service suite |
| End-to-end smoke | `make functional-smoke` | Docker-backed critical-loop smoke |
| Full critical path | `make critical-path-validation` | Canonical single-command evidence path |
| Stop stack | `make down` | Always run during cleanup |

All CI consumers should prefer these Make targets over inline command variants.

## Expected Service Contract

The Docker stack exposes the agent APIs on the host as:

- Context Agent: `http://localhost:5003`
- Policy Agent: `http://localhost:5002`
- Validator Agent: `http://localhost:5001`

Each service must answer both `GET /health` and `GET /ready`. CI gates should
treat `/ready` as the traffic gate and readiness failure source. `/health`
alone is not enough evidence for service-to-service execution.

## Proposed INIT-04 Gate Order

1. Install or restore Python dependencies for host-side tooling.
2. Run `make lint`.
3. Run `make host-fast-tests`.
4. Run `make up`.
5. Verify readiness on `5003`, `5002`, and `5001`.
6. Run `make context-tests`, `make policy-tests`, and `make validator-tests`.
7. Run `make policy-rag-validate` when the PR touches policy-agent RAG
   manifest, collection naming, Chroma wiring, or source paths.
8. Run `make functional-smoke`.
9. Promote `make critical-path-validation` once runtime and duration are stable
   enough for the target branch policy.
10. Run `make down` in cleanup even after failures.

## Informational First Gates

Start these as informational until INIT-04 has enough runtime history:

- `make functional-smoke`
- `make critical-path-validation`
- RAG collection validation that depends on local Chroma state or heavyweight
  model/bootstrap behavior

Good promotion signals:
- failures are actionable from retained artifacts
- command duration is acceptable for PR feedback
- retry behavior is not masking real runtime defects
- logs avoid secret disclosure

## Failure Artifacts

Retain these artifacts or log sections for failed Docker gates:

- `migration/functional-smoke-result.json`
- smoke script error output, when present in the job log
- Compose service status after failure
- agent logs for `context_agent_web`, `policy_agent_service`, and
  `validator_agent_service`
- Mongo logs for `context_mongo`
- Chroma logs from the Compose `chroma` service
- readiness responses for `http://localhost:5003/ready`,
  `http://localhost:5002/ready`, and `http://localhost:5001/ready`

Artifact retention must redact secrets and should not publish raw environment
values.

## Non-Interactive Requirements

Commands used by CI must run without prompts or TTY allocation. Current
CI-facing candidates are non-interactive:

- `make lint`
- `make host-fast-tests`
- `make up`
- `make context-tests`
- `make policy-tests`
- `make policy-rag-validate`
- `make validator-tests`
- `make functional-smoke`
- `make critical-path-validation`
- `make down`

Avoid shell targets intended for humans, such as service shell targets, in CI.

## Open Handoff Questions For INIT-04

- Which Docker gates become required immediately, and which remain
  informational for one or more releases?
- What runtime budget is acceptable for PR checks on GitHub-hosted runners?
- Which artifacts should be retained for pull requests versus protected branch
  runs?
- Whether RAG validation should use cached fixtures, opt-in jobs, or a later
  INIT-15 benchmark path before becoming required.
