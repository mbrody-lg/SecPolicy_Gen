# A2A and MCP Protocol Profile

Status: accepted for bounded evaluation
Initiative: INIT-25
Date: 2026-07-21

## Context

SecPolicyGen already has explicit contracts between Context Agent, Policy
Agent, Validator Agent, and the application workflow. Docker Agent/cagent is a
candidate runtime, but changing runtimes must not move domain ownership or
create a second source of workflow state.

A2A and MCP solve different interoperability problems:

- A2A supports delegation to an independent agent through discoverable skills,
  tasks, progress, cancellation, and structured results.
- MCP exposes bounded tools and contextual resources to an agent.

They complement the current service APIs; neither replaces every HTTP route.

## Decision

Adopt A2A and MCP incrementally behind protocol-neutral domain ports:

1. Keep Application Workflow authoritative for durable state, transitions,
   retries, cancellation policy, persistence, and user-visible progress.
2. Evaluate A2A first with a stateless Validator candidate in shadow mode.
3. Evaluate MCP first with one read-only RAG evidence retrieval tool.
4. Consider Policy Agent over A2A only after the Validator pilot passes.
5. Consider Context Intelligence last, where A2A `INPUT_REQUIRED` may support
   multi-turn context building.
6. Keep the current HTTP path authoritative until a separate cutover decision.

The target protocol profiles are A2A 1.0 and MCP `2025-11-25`. Adapters must
negotiate and verify the capabilities of the pinned Docker Agent runtime rather
than infer support from the target version.

## Ownership Boundaries

| Concern | Owner | Protocol role |
| --- | --- | --- |
| Workflow state and transitions | Application Workflow | A2A task state is a projection |
| Context analysis | Context Agent | Future A2A candidate |
| Evidence retrieval and indexing | RAG Runtime | Read-only MCP tool first |
| Policy generation | Policy Agent | Future A2A candidate |
| Policy validation | Validator Agent | First A2A shadow candidate |
| UI commands and progress | Policy Workflow UI/API | Existing HTTP/SSE |
| Health, readiness, metrics | Runtime Infrastructure | Existing HTTP/Prometheus |
| Persistence | Owning bounded context | Never exposed as generic MCP tools |

The Coordinator in the target contract pack is a logical Application Workflow
responsibility. It is not an LLM agent or an externally discoverable A2A agent.

## A2A Profile

### Initial Agent Card

The pilot exposes one agent and one skill:

- agent: `secpolicy-validator-shadow`;
- skill: `validate_security_policy`;
- input: existing `validator.validation_payload` contract;
- output: existing `validator.validation_decision` contract;
- side effects: none.

Docker Agent YAML `skills` load runtime instructions and are not equivalent to
skills advertised by an A2A Agent Card. The adapter must map them explicitly.

### Identity and correlation

- A2A `contextId` groups one workflow run; it is not an authorization boundary.
- A2A `taskId` identifies a candidate attempt and references the authoritative
  `pipeline_job_id`.
- Domain identifiers, schema versions, ownership, and `policy_content_hash`
  remain inside domain contracts.
- `X-Correlation-ID` and `traceparent` are propagated independently.

### Task state mapping

| SecPolicyGen state | A2A state |
| --- | --- |
| `queued` | `SUBMITTED` |
| running, generating, validating | `WORKING` |
| user information required | `INPUT_REQUIRED` |
| delegated authorization required | `AUTH_REQUIRED` |
| execution completed | `COMPLETED` |
| execution error | `FAILED` |
| cancelled | `CANCELED` |
| refused or unsupported | `REJECTED` |

Validator outcomes `accepted`, `review`, and `rejected` remain domain data. A
successful validation that rejects a policy is an A2A `COMPLETED` task.

### Results and runtime compatibility

A2A transports versioned SecPolicyGen contracts; it does not redefine them.
Use A2A artifacts when the pinned runtime proves support. Until then, strict
structured JSON in a Message is acceptable when the adapter validates the same
domain schema.

The first pilot uses polling or supported streaming. Push notifications,
dynamic discovery, subagents, and agent memory are out of scope.

## MCP Profile

The first MCP facade exposes only:

- tool: `rag.retrieve_evidence`;
- behavior: read-only, bounded `top_k`, allowlisted metadata filters;
- output: versioned `rag.retrieval_evidence` references and bounded excerpts;
- side effects: none.

The facade must not expose arbitrary Chroma queries, collection administration,
RAG refresh/reindex, Mongo CRUD, raw logs, internal prompts, provider responses,
or unbounded documents.

Remote-capable resources may be added after tenant isolation exists, for
example `secpolicy://norms/catalog` and tenant-scoped evidence references.
Prompts and mutable tools are deferred until a concrete consumer requires them.

## Security Profile

No remote A2A or MCP exposure is allowed before INIT-11 provides service
identity and tenant binding.

Required controls:

- TLS outside loopback and authenticated identity on every request;
- explicit audience, tenant, object, action, and skill/tool authorization;
- short-lived credentials and no downstream token passthrough;
- preconfigured allowlisted Agent Cards and outbound destinations;
- request-size, deadline, concurrency, replay, and idempotency controls;
- MCP Origin validation for Streamable HTTP;
- no policy, context, evidence text, prompts, or tokens in logs;
- negative tests for cross-tenant access, SSRF, replay, and wrong scopes.

Initial scopes are deliberately narrow:

- `rag.evidence.read`;
- `policy.candidate.validate`;
- `policy.candidate.generate` only in a later phase.

## Error and Progress Contract

Protocol adapters normalize transport errors into the existing runtime error
contract. They must preserve:

- stable error code and retryability;
- correlation, protocol task/session ID, and workflow phase;
- safe user-facing summary and protected development diagnostics;
- deadlines and effective provider cancellation.

A2A updates may enrich existing pipeline events, but cannot advance or repair
the authoritative workflow directly.

## Evaluation and Rollback

Candidate execution is shadow-only and no-write. Each candidate receives the
same fixture as the authoritative implementation and emits a `parity_report`
covering schema, policy hash, decision, evidence coverage, errors, latency, and
mutations.

Independent controls are required:

- `A2A_SHADOW_ENABLED`;
- `MCP_RAG_SHADOW_ENABLED`;
- independent traffic percentages;
- legacy path enabled by default;
- no data migration or dual writes;
- tested disablement and recovery in under five minutes.

## Admission Gates

The bounded pilot requires:

1. Docker-backed protocol and capability negotiation evidence.
2. Producer/consumer contract tests using golden fixtures.
3. INIT-11 identity, tenant, audience, and scope enforcement.
4. Verified zero candidate writes and no downstream callbacks.
5. Observable correlation, progress, cancellation, and fallback.
6. Semantic parity gates; generated prose is not compared byte-for-byte.

Stop immediately for a candidate write, tenant or secret leakage, ineffective
cancellation, non-allowlisted egress, protocol conformance failure, false
`accepted` result, or regression of the authoritative path.

Narrow or pause when the pilot does not enable a real second consumer or does
not reduce coordination/runtime coupling enough to justify its operational
cost.

## Consequences

- Positive: standard agent interoperability without coupling domain services
  to Docker Agent.
- Positive: RAG can become reusable through a narrow evidence contract.
- Cost: protocol conformance, identity, observability, and operational testing.
- Constraint: Docker Agent A2A support is evolving, so runtime capability
  evidence is required before every expansion.

## References

- [A2A specification](https://a2a-protocol.org/latest/specification/)
- [MCP specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [Docker Agent A2A support](https://docs.docker.com/ai/docker-agent/features/a2a/)
- [Target agent contract pack](./target-agent-contract-pack.md)
