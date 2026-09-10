# Target Agent Contract Pack

This contract pack defines the target SecPolicyGen agent team before Docker
Agent/cagent migration work continues.

The product goal is an agent-based system that creates security policies from
enterprise context, applicable regulation, retrieved evidence, policy
generation, and validation feedback. Runtime tooling must serve that workflow;
it must not become the owner of domain behavior.

## Runtime Reference

Topology and ownership are governed by
[`ADR 0001`](../adr/0001-cagent-runtime-topology-and-workflow-ownership.md).

Docker Agent/cagent is evaluated as a runtime and packaging option with these
capabilities:

- declarative YAML/HCL agent configuration;
- multi-agent coordination through coordinators, sub-agents, handoffs, and
  optional background agents;
- RAG tool support for governed knowledge bases;
- structured output for machine-readable downstream artifacts;
- permission controls for filesystem, shell, network, and tool execution;
- API execution only behind explicit auth, observability, and rollback gates.

Google/Gemini is treated as a model provider option, not as a separate cagent
runtime, unless a different project reference is supplied.

## Agent Team

| Agent | Owns | Produces |
| --- | --- | --- |
| Application Workflow | Durable run state, business transitions, cancellation, retry policy, handoff order | `workflow_state`, `agent_handoff`, `runtime_error` |
| Candidate Coordinator | Bounded non-authoritative Policy-Validator coordination | Candidate artifact references and runtime status |
| Context Agent | Enterprise context intake, context-building updates, planning input, final context | `security_context.v1`, `context_agent.phase_output`, `context_agent.policy_handoff.v1` |
| Regulatory/RAG Agent | Applicable source selection, retrieval planning, evidence bundle | `rag.retrieval_context`, `rag.retrieval_plan`, `rag.retrieval_evidence` |
| Policy Agent | Policy draft generation from approved context and evidence | `policy_agent.policy_draft` |
| Validator Agent | Grounding, completeness, consistency, and regeneration feedback | `validator.validation_payload`, `validator.validation_decision` |
| Runtime Adapter | Docker Agent/cagent invocation, permissions, logs, correlation, shadow execution | `runtime_invocation`, `parity_report` |

## Artifact Contracts

Use current service contracts as the source of truth. Docker Agent/cagent
configs may reference these contracts, but must not redefine them.

This pack has three contract layers:

| Layer | Meaning | Change rule |
| --- | --- | --- |
| Current service contract | Already produced or accepted by `context-agent`, `policy-agent`, or `validator-agent` | Must match current code and tests |
| Compatibility bridge | Explicit adapter shape between current services | May be tightened only with producer and consumer tests |
| Target runtime artifact | Required for Docker Agent/cagent dry-run, shadow mode, parity, or cutover | Must not be treated as current service behavior until implemented |

Target runtime artifacts should include these envelope fields when practical:

- `schema_version`;
- `artifact_id`;
- `context_id` when available;
- `correlation_id`;
- `created_at`;
- `producer`;
- `status`;
- `errors`.

Do not require this envelope on current service contracts that already use a
different version field, for example `security_context.v1`.

## Required Artifacts

### `workflow_state`

Tracks the current workflow phase and available actions.

Layer: target runtime artifact.

Required fields:

- `phase`: `intake`, `context_building`, `planning`, `execution`,
  `final_context`, `policy_generation`, `validation`, `completed`, or `failed`;
- `allowed_actions`;
- `blocked_actions`;
- `last_completed_step`;
- `next_expected_action`;
- `progress`;
- `correlation_id`;
- `diagnostics_url` when available.

### `security_context.v1`

Represents the approved enterprise security context.

Layer: current service contract.

Required fields:

- `version`;
- `profile`;
- `information_assets`;
- `compliance`;
- `security_posture`;
- `policy_intent`;
- `analysis`;
- `retrieval_hints`.

Key reusable fields include:

- `profile.sector`, `activity`, `region`, `operating_countries`, `languages`,
  `business_model`, and `service_type`;
- `information_assets.important_assets`, `critical_assets`,
  `data_categories`, `third_party_dependencies`, and `cloud_services`;
- `policy_intent.need`, `policy_type`, `scope`, `audience`, and `specificity`;
- `analysis.facts`, `missing_information`, and `confidence`;
- `retrieval_hints.collection_families`, `jurisdictions`, `sectors`,
  `data_types`, and `methodologies`.

### `context_agent.phase_output`

Represents Context Agent phase outputs.

Layer: current service contract.

Current artifacts:

- `context_building`;
- `context_planning`;
- `context_task_result`;
- `final_context`.

Reusable fields:

- `summary`;
- `explicit_facts`;
- `assumptions`;
- `missing_information`;
- `follow_up_questions`;
- `tasks`;
- `findings`;
- `risks`;
- `policy_implications`;
- `rag_retrieval_hints`;
- `sections`;
- `unresolved_gaps`;
- `policy_handoff`.

Phase-specific required fields remain owned by
`context-agent/app/context_output_schemas.py`. This pack must not collapse
those phase schemas into a single shared schema.

### `policy_agent.business_context`

Represents the current compatibility bridge from Context Agent to Policy Agent.

Layer: compatibility bridge.

Context Agent should emit these fields when available:

- `country`;
- `region`;
- `sector`;
- `important_assets`;
- `critical_assets`;
- `current_security_operations`;
- `methodology`;
- `generic`;
- `need`;
- `data_types`;
- `retrieval_collection_families`.

Policy Agent currently requires only its generation payload core fields and
treats `business_context` as optional/open-shaped. Tightening this bridge
requires producer and consumer tests in the same PR.

### `context_agent.policy_handoff.v1`

Represents the final approved handoff from Context Agent to Policy Agent.

Layer: current service contract.

Required fields:

- `version`;
- `source`;
- `contract`;
- `security_context_version`;
- `final_context_version`;
- `final_context_status`;
- `context_ready_for_policy`;
- `plan_revision_id`;
- `context_snapshot_hash`;
- `business_context`;
- `final_context_sections`;
- `structured_findings`;
- `retrieval_hints`;
- `assumptions`;
- `unresolved_gaps`.

Validation-critical conditions:

- exact `version` is supported by Context Agent;
- `contract` is `context_agent.policy_handoff`;
- `source` is `context-agent`;
- `security_context_version` matches the current security context version;
- `final_context_version` matches the current final context version;
- `final_context_status` is `ready`;
- `context_ready_for_policy` is `true`;
- `plan_revision_id` is not empty;
- `context_snapshot_hash` is not empty;
- final context sections are accepted;
- final context sections have non-empty content;
- structured findings are completed;
- structured findings have stable `task_id` values;
- findings expose structured evidence or legacy content;
- `unresolved_gaps` is empty;
- `retrieval_hints.collection_families` is not empty.

### `rag.retrieval_context`

Represents the normalized policy-generation input used for retrieval planning.

Layer: current service contract.

Required fields:

- `context_id`;
- `refined_prompt`;
- `language`;
- `country`;
- `region`;
- `sector`;
- `important_assets`;
- `critical_assets`;
- `methodology`;
- `specificity`;
- `need`;
- `data_types`.

Current behavior derives `data_types` from prompt, sector, methodology, and
need. Treat provided `business_context.data_types` as input intent until Policy
Agent explicitly consumes it.

### `rag.retrieval_plan`

Represents deterministic collection-specific retrieval planning.

Layer: current service contract.

Required fields:

- `context_id`;
- `steps`;
- `required_families`;
- `coverage_notes`.

Each step must include `family`, `collection`, `query`, `filters`, and `top_k`.

### `rag.retrieval_evidence`

Carries the regulatory and methodology evidence used by policy generation.

Layer: current service contract.

Required fields:

- `text`;
- `source_id`;
- `collection`.

Optional or derived fields:

- `family`;
- `document_id`;
- `score`;
- `citation`;
- `metadata`.

### `policy_agent.policy_draft`

Represents generated policy content before validation.

Layer: current service contract.

Required fields:

- `context_id`;
- `language`;
- `policy_text`;
- `structured_plan`;
- `generated_at`;
- `policy_agent_version`;
- `retrieval_evidence`.

### `validator.validation_payload`

Represents the payload Validator Agent must be able to validate.

Layer: current service contract.

Required fields:

- `context_id`;
- `policy_text`;
- `structured_plan`;
- `generated_at`.

Optional fields:

- `language`;
- `policy_agent_version`;
- `retrieval_evidence`;
- `correlation_id`.

### `validator.validation_decision`

Represents validator output.

Layer: current service contract.

Required fields:

- `status`: `accepted`, `review`, or `rejected`;
- `reasons`;
- `recommendations`.

Optional fields:

- `evaluator_analysis`;
- `retrieval_evidence`;
- `correlation_id`.

Target validation extensions:

- `evidence_gaps`;
- `context_gaps`;
- `policy_gaps`;
- `regeneration_instructions`.

These target extensions require implementation and tests before they can be
treated as validator output.

### `runtime_invocation`

Represents one Docker Agent/cagent execution attempt.

Layer: target runtime artifact.

Required fields:

- `runtime`;
- `runtime_version`;
- `agent_config_ref`;
- `agent_name`;
- `mode`: `dry_run` or `shadow`; a future contract revision may introduce a
  cutover candidate only after the ADR gates pass;
- `input_artifact_ids`;
- `output_artifact_ids`;
- `permission_profile`;
- `started_at`;
- `finished_at`;
- `exit_status`;
- `logs_ref`;

### `parity_report`

Compares current authoritative execution with Docker Agent/cagent execution.

Layer: target runtime artifact.

Required fields:

- `case_id`;
- `contract_compatible`;
- `artifact_differences`;
- `evidence_coverage`;
- `validation_difference`;
- `runtime_errors`;
- `timing`;
- `observability`;
- `security_findings`;
- `recommendation`: `continue`, `narrow`, or `pause`; this is contract-level
  compatibility and never authorizes cutover.

New reports also include `assessment` with:

- `contract_recommendation`, equal to the legacy `recommendation` field;
- `semantic_readiness`: `not_assessed` or `not_ready`;
- `cutover_readiness`: currently only `not_ready`;
- `evidence_basis.authoritative`: `projected`, `observed`, or `unverified`;
- `evidence_basis.candidate`: `simulated`, `live`, or `unverified`.

Legacy reports without `assessment` prove contract compatibility only.
Projected, simulated, or unverified evidence cannot claim semantic or cutover
readiness. A future contract revision may introduce `ready` only together with
structured semantic evidence and verified observability.

### `loop.observability`

Represents cross-service traceability for current and candidate runtimes.

Layer: current service contract.

Required fields:

- `event`;
- `service`;
- `stage`;
- `result`.

Optional fields when available and safe:

- `X-Correlation-ID`;
- `correlation_id`;
- `context_id`;
- `route`;
- `method`;
- `status_code`;
- `error_code`;
- `duration_ms`;
- `timeout_seconds`.

### `loop.evidence_artifact`

Represents attachable runtime validation evidence.

Layer: current service contract.

Current artifact:

- `migration/functional-smoke-result.json`.

Required fields:

- `schema_version`;
- `run`;
- `environment`;
- `service_checks`;
- `preflight_failures`;
- `contexts`;
- `summary`;
- `failures`.

## Handoff Rules

- Application Workflow owns durable state. During the pilot, Context Agent
  pipeline jobs and events implement this logical boundary.
- A candidate coordinator may route a bounded Policy-Validator attempt, but it
  must not invent domain outputs, persist authoritative state, or choose retry
  policy. Application Workflow supplies the authorized retry limit.
- Context Agent may request more user context during context building or
  planning.
- Regulatory/RAG Agent may retrieve and summarize evidence, but must not draft
  policy text.
- Policy Agent may generate from approved context and evidence only.
- Validator Agent may reject or request regeneration, but must not mutate the
  approved context.
- Runtime Adapter may execute Docker Agent/cagent in dry-run or shadow mode,
  but must not become the authoritative workflow state.

## Permission Rules

- Default runtime posture is read-only, dry-run, and shadow-mode.
- Deny destructive shell operations by default.
- Deny secret, `.env`, database dump, and private key reads unless a specific
  reviewed task requires them.
- Require explicit review before enabling write access, network access,
  service mutation, or production-like execution.
- Runtime permission changes require negative-path tests or documented manual
  security review.

## PR #16 And PR #17 Disposition

PRs #16 and #17 are superseded by the #109-#115 stack and must not be merged.
Close them after the replacement disposition is accepted. Prompt files, YAML,
shadow runners, and summaries remain implementation assets rather than
canonical business contracts.

## INIT-25 Decision Gates

Use these gates before expanding Docker Agent/cagent scope.

### Continue

Continue contract evaluation when:

- dry-run output validates the current service contracts or explicitly marked
  target runtime artifacts;
- shadow mode is non-authoritative and produces useful parity reports;
- Docker Agent/cagent reduces orchestration, packaging, observability, or
  runtime-permission complexity;
- rollback remains simpler than the migration path.

This decision does not authorize cutover. Cutover additionally requires
observed authoritative evidence, live candidate evidence, semantic readiness,
and the operational gates below.

### Narrow

Narrow migration to adapter experiments when:

- Docker Agent/cagent is useful for one bounded context but not the whole
  product workflow;
- YAML prompts or runtime scripts start duplicating domain contracts;
- parity evidence is useful but not stable enough for CI promotion;
- runtime permissions require more access than the current architecture.

### Pause

Pause migration when:

- Docker Agent/cagent scaffolding mainly reproduces current implementation
  details without improving the final product workflow;
- target artifacts cannot be validated against deterministic fixtures;
- shadow execution mutates authoritative state;
- runtime auth, permission, observability, or rollback gates are unclear.

## Acceptance Gates

Before any Docker Agent/cagent cutover:

- target artifacts have deterministic fixture coverage;
- dry-run output validates against the contract pack;
- shadow runs do not mutate authoritative state;
- parity reports include evidence coverage and validation differences;
- authoritative and candidate runs share the same canonical input hash;
- semantic artifacts are observed rather than projected, with accepted quality
  thresholds for applicability, evidence, citations, unsupported claims, and
  validation decisions;
- service identity, authorization, and tenant isolation are enforced;
- runtime permissions are explicit and reviewed;
- errors are observable through correlation ids and diagnostics;
- rollback instructions exist and have been tested or reviewed.
