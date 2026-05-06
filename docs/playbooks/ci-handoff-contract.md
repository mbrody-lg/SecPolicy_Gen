# CI Handoff Contract For Docker Gates

Use this contract when preparing INIT-04 GitHub Actions work that will consume
the local Docker validation path established by INIT-01.

This document is a handoff only. It does not implement CI workflows, change
Makefile targets, or modify Compose behavior.

Use [Environment Configuration Contract](./environment-configuration.md) as the
source of truth for variable ownership, defaults, and validation expectations.
This playbook only translates that contract into downstream CI and service-auth
decisions.

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

## INIT-02 Environment Handoff

INIT-02 leaves CI with two distinct configuration modes:

- deterministic local/CI validation using fake local values and mock provider
  configs;
- opt-in real-provider validation using GitHub Actions secrets and explicit job
  conditions.

Deterministic jobs must not require real OpenAI or Mistral credentials. They can
consume `.env.example`, CI-provided fake values, or repository variables whose
values are safe to print. Real-provider jobs must be opt-in, non-blocking until
INIT-04 promotes them, and must not publish raw provider responses or errors.

### GitHub Actions Secrets

Treat these as repository or environment secrets when INIT-04 introduces
workflow files:

| Secret | Purpose | Required by default gates |
|--------|---------|---------------------------|
| `FLASK_SECRET_KEY` | Flask session signing for non-test runtime paths | No; deterministic gates may use fake local values |
| `OPENAI_API_KEY` | OpenAI-backed provider execution | No; only opt-in real-provider jobs |
| `MISTRAL_API_KEY` | Mistral-backed validator execution | No; only opt-in real-provider jobs |

Provider secrets should be available only to protected or explicitly approved
jobs. They should never be used by pull-request checks from untrusted forks.

### GitHub Actions Variables Or Job Env

Use repository variables, job-level environment, or generated CI env files for
non-secret values:

| Variable group | Examples | CI handling |
|----------------|----------|-------------|
| Flask/runtime | `FLASK_ENV`, `DEBUG`, `TESTING`, `FLASK_RUN_DEBUG` | Keep debug off by default; enable testing only for host test jobs |
| Service URLs | `POLICY_AGENT_URL`, `VALIDATOR_AGENT_URL`, `OPENAI_API_URL`, `MISTRAL_API_URL` | Keep internal Compose URLs for container jobs and localhost URLs for host checks |
| Persistence | `MONGO_URI`, `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_READINESS_MODE` | Use Compose defaults for Docker gates unless a job intentionally overrides them |
| RAG config | `RAG_SOURCES_PATH`, `RAG_VALIDATE_CHROMA`, `POLICY_AGENT_ALLOW_MODEL_DOWNLOAD`, `METADATA_SCHEMA_PATH` | Keep lightweight validation required; keep downloads/heavy indexing opt-in |
| HTTP safety | `MAX_CONTENT_LENGTH`, `SESSION_COOKIE_SECURE`, `TRUSTED_HOSTS` | Use documented local-safe values for local Docker gates; revisit production values under deployment work |
| Smoke/readiness | readiness URLs, timeout/retry knobs, artifact paths | Keep deterministic and non-interactive; redact failure output |

Avoid adding new service-auth variables under INIT-02. Shared tokens, JWT
signing keys, mTLS material, service identities, and authorization headers are
owned by INIT-11.

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

Initial branch protection should start with the deterministic gates that have
clear failure ownership: lint, fast host tests, Compose config validation,
`make up`, readiness checks, and service suites. Functional smoke and the full
critical path can become required after INIT-04 has runtime history and stable
artifact retention.

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

## INIT-11 Service-Auth Boundary

INIT-02 deliberately does not define service-to-service authentication. When
INIT-11 starts, it should reuse the secret-handling rules from the environment
contract but define its own mechanism and variables.

INIT-11 should decide:

- the service identity model;
- whether the first mechanism is a shared secret header, signed token, mTLS, or
  another project-appropriate control;
- how auth failures are represented in readiness, health, and smoke artifacts;
- which new secrets belong in GitHub Actions and which are deployment-only;
- how to rotate service-auth material without changing app code.

Until INIT-11 lands, CI must not invent placeholder auth headers or mark
service-auth checks as required.

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
- Which job, if any, may access real-provider secrets, and under what branch or
  manual approval condition?
- Whether the CI environment should generate a temporary env file from the
  contract or inject variables directly at the job level.
