# Target Agent Contract Pack

This contract pack defines the target SecPolicyGen agent team before Docker
Agent/cagent migration work continues.

The product goal is an agent-based system that creates security policies from
enterprise context, applicable regulation, retrieved evidence, policy
generation, and validation feedback. Runtime tooling must serve that workflow;
it must not become the owner of domain behavior.

## Runtime Reference

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
| Coordinator | Workflow routing, handoff order, run state, stop conditions | `workflow_state`, `agent_handoff`, `runtime_error` |
| Context Agent | Enterprise context intake, context-building updates, planning input, final context | `security_context.v1`, `context_agent.phase_output`, `context_agent.policy_handoff.v1` |
| Regulatory/RAG Agent | Applicable source selection, retrieval planning, evidence bundle | `rag.retrieval_context`, `rag.retrieval_plan`, `rag.retrieval_evidence` |
| Policy Agent | Policy draft generation from approved context and evidence | `policy_agent.policy_draft` |
| Validator Agent | Grounding, completeness, consistency, and regeneration feedback | `validator.validation_payload`, `validator.validation_decision` |
| Runtime Adapter | Docker Agent/cagent invocation, permissions, logs, correlation, shadow execution | `runtime_invocation`, `parity_report` |

## Artifact Contracts

All artifacts must include:

- `schema_version`;
- `artifact_id`;
- `context_id` when available;
- `correlation_id`;
- `created_at`;
- `producer`;
- `status`;
- `errors`.

Use current service contracts as the source of truth. Docker Agent/cagent
configs may reference these contracts, but must not redefine them.

## Required Artifacts

### `workflow_state`

Tracks the current workflow phase and available actions.

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

### `policy_agent.business_context`

Represents the current compatibility bridge from Context Agent to Policy Agent.

Required fields:

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

### `context_agent.policy_handoff.v1`

Represents the final approved handoff from Context Agent to Policy Agent.

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

- `contract` is `context_agent.policy_handoff`;
- `source` is `context-agent`;
- final context sections are accepted;
- structured findings are completed;
- `unresolved_gaps` is empty;
- `retrieval_hints.collection_families` is not empty.

### `rag.retrieval_context`

Represents the normalized policy-generation input used for retrieval planning.

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

### `rag.retrieval_plan`

Represents deterministic collection-specific retrieval planning.

Required fields:

- `context_id`;
- `steps`;
- `required_families`;
- `coverage_notes`.

Each step must include `family`, `collection`, `query`, `filters`, and `top_k`.

### `rag.retrieval_evidence`

Carries the regulatory and methodology evidence used by policy generation.

Required fields:

- `text`;
- `source_id`;
- `collection`;
- `family`;
- `document_id`;
- `score`;
- `citation`;
- `metadata`.

### `policy_agent.policy_draft`

Represents generated policy content before validation.

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

Required fields:

- `decision`: `accepted`, `review`, or `rejected`;
- `reasons`;
- `recommendations`;
- `evidence_gaps`;
- `context_gaps`;
- `policy_gaps`;
- `regeneration_instructions`;

### `runtime_invocation`

Represents one Docker Agent/cagent execution attempt.

Required fields:

- `runtime`;
- `runtime_version`;
- `agent_config_ref`;
- `agent_name`;
- `mode`: `dry_run`, `shadow`, or `cutover_candidate`;
- `input_artifact_ids`;
- `output_artifact_ids`;
- `permission_profile`;
- `started_at`;
- `finished_at`;
- `exit_status`;
- `logs_ref`;

### `parity_report`

Compares current authoritative execution with Docker Agent/cagent execution.

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
- `recommendation`: `continue`, `narrow`, or `pause`.

### `loop.observability`

Represents cross-service traceability for current and candidate runtimes.

Required fields:

- `X-Correlation-ID`;
- `correlation_id`;
- `context_id`;
- `event`;
- `service`;
- `stage`;
- `result`;
- `route`;
- `method`;
- `status_code`;
- `error_code`;
- `duration_ms`;
- `timeout_seconds`.

### `loop.evidence_artifact`

Represents attachable runtime validation evidence.

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

- Coordinator may route work, but it must not invent domain outputs.
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

PR #16 can continue only if it is rebased or replaced so the dry-run scaffold
validates this contract pack. Prompt files and YAML are implementation assets,
not canonical business contracts.

PR #17 can continue after the PR #16 decision. Shadow-mode runners and
summaries are useful only if they compare current authoritative execution
against the target artifacts above.

## Acceptance Gates

Before any Docker Agent/cagent cutover:

- target artifacts have deterministic fixture coverage;
- dry-run output validates against the contract pack;
- shadow runs do not mutate authoritative state;
- parity reports include evidence coverage and validation differences;
- runtime permissions are explicit and reviewed;
- errors are observable through correlation ids and diagnostics;
- rollback instructions exist and have been tested or reviewed.
