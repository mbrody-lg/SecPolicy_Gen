# ADR 0001: Cagent Runtime Topology And Workflow Ownership

- Status: Accepted for bounded evaluation
- Date: 2026-07-16
- Initiative: INIT-25

## Context

The current INIT-25 stack proves contract and fail-closed behavior, but Python
still sequences four Docker Agent leaves and the parity report compares
contract shape rather than semantic output. Promoting that scaffold would add
an orchestrator without removing an existing responsibility.

## Decision

- Application Workflow is the sole owner of durable run state, transitions,
  cancellation, retries, and business routing. During the pilot this logical
  boundary remains implemented by Context Agent pipeline jobs and events.
- Context, RAG, Policy, and Validator retain ownership of their domain rules
  and artifacts. The UI displays state and sends commands; it does not own the
  workflow.
- Docker Agent remains behind a non-authoritative execution port. It may
  coordinate one bounded Policy-Validator candidate loop, but cannot persist
  authoritative state, redefine domain contracts or prompts, or select product
  phases. Application Workflow supplies the retry policy and limit; Docker
  Agent executes only the authorized attempt and returns its result.
- The pilot topology is one dedicated `docker agent serve api` runtime called
  by the adapter. The four CLI subprocess scaffold is evaluation evidence, not
  the target topology.
- The current service path remains the baseline and immediate rollback path.
- Docker Sandboxes remain optional for local isolation until private-service
  networking is proven. A connected runtime must run as a dedicated non-root
  container with resource limits, controlled egress, an allowlisted internal
  network, and no Docker socket or host-filesystem access. It also requires
  explicit service auth, allowlisted capabilities, deadlines, idempotency, and
  no authoritative writes.
- Runtime version, commit, schema, and distributed asset digests must be pinned
  and upgraded together. Automatic runtime or tool installation is disabled.

## Alternatives Considered

| Alternative | Decision |
| --- | --- |
| Keep the current architecture without Cagent | Permanent baseline and rollback |
| Four CLI processes sequenced by Python | Rejected as the target topology |
| One Docker Agent API for a Policy-Validator pilot | Selected conditionally |
| Migrate Context, RAG, Policy, and Validator together | Rejected |
| Let Cagent own durable workflow state | Rejected |
| Extract an Application Workflow microservice now | Deferred; establish the logical boundary first |

## Consequences

- PRs #109-#112 remain reusable contract-test foundations.
- PR #113 remains an experimental configuration asset.
- PRs #114-#115 must be adapted to the API topology before promotion.
- PRs #16-#17 remain superseded.
- A contract-level `continue` never authorizes cutover. Semantic and operational
  evidence require separate gates.

## Pilot Exit Gates

Continue to the vertical pilot only when:

- the candidate uses real, non-mutating Policy and Validator capabilities;
- one component remains the durable workflow owner;
- projected or simulated evidence cannot claim semantic or cutover readiness;
- service identity, authorization, tenant isolation, observability, deadlines,
  cancellation, and rollback are testable;
- the pilot removes or simplifies an existing coordination responsibility.

Otherwise INIT-25 remains paused at the runtime boundary.
