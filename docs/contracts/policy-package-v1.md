# Policy Package V1: structured proposal contract

This additive W06 contract is a pure wire format. It does not activate a new
runtime path, call a provider, authorize a tenant, or confer legal approval.
`contracts/policy_package_v1.py` is the executable 1.0 definition; the JSON
fixture in `tests/fixtures/policy_package_v1.synthetic.json` is synthetic.

## Ownership and binding

Context owns the approved `PolicyRequestV1` input. Policy owns the generation
profile, coverage plan, budget estimate and package proposal. Validator reads
the structured package plus the same plan/profile/quote; it need not parse
Markdown to find requirements or citations. Application Workflow owns revision
state and expert decisions, not these pure validators.

Every object has an exact `contract` and `version=1.0`, rejects unknown fields,
and is capped at 256 KiB serialized. IDs use lowercase ASCII, a stable type
prefix (`sec-`, `req-`, `unit-`, `ev-`, `act-`, `rev-`, `cov-`, `profile-`,
`plan-`, `quote-`, `source-`, `conflict-`, `gap-`), and at most 96 characters. IDs are
assigned by their canonical owner, never derived from retrieval rank or prose
position. An existing ID must survive a text edit that preserves its semantic
unit. A changed package gets a new `revision_id` and optional
`previous_revision_id`; the package itself does not approve either revision.

`policy_request_hash` binds all four contracts to one approved input hash.
`profile_id` and `coverage_plan_id` bind the downstream records. The plan's
`source_inventory_hash` must match package provenance. Runtime must also
compare these values to authoritative tenant-bound records; self-consistent
payloads are not proof of authorization. These schemas do not import the
pending PolicyRequest 1.1 extension.

## Shapes

- `GenerationProfileV1`: independent `document_profile`, `coverage_mode`,
  `effort_tier`, language and hard count ceilings. The tier controls method,
  not mandatory safety/coverage.
- `CoveragePlanV1`: one disposition per source unit (`applicable`,
  `conditional`, `not_applicable`, `undetermined`), mandatory/optional flag,
  rationale, fact/rule IDs, evidence and planned requirement IDs. Unresolved
  gaps and conflicts remain explicit. An applicable mandatory unit must have
  a requirement; undetermined and not-applicable units cannot have one.
  Conditional or undetermined mandatory units require `review_required` and
  a linked, unit-specific gap with a reason and review owner. A gap is not
  approval or proof of applicability; downstream gates must hold or route it
  for human review rather than silently treating it as covered.
- `PolicyPackageV1`: purpose and scope, stable sections, requirements,
  evidence, implementation actions, assumptions, typed exclusions, conflicts,
  exception process, review cadence, provenance and bounded machine-readable
  error records. Mandatory requirements must link evidence. Every requirement
  must have an implementation action or an explicit `no_action_reason`; a
  package-wide empty action list is acceptable only when each requirement has
  such a reason. Evidence stores
  source/unit IDs, version, locator and digests; no raw corpus text is needed
  for structural validation. Grounding evidence must belong to a source unit
  in the plan and be referenced by that plan. Separate candidate evidence must
  declare `role=candidate` and a reason, use an unplanned source unit, and
  cannot be linked to a plan item or requirement. Candidate evidence is not a
  citation or normative grounding. Section `body` is a derived rendering
  input, not the source of requirement identities.
- `GenerationBudgetQuoteV1`: currency, catalog version, estimate, upper bound,
  cap and call/token limits. `estimated_amount` and
  `unrounded_upper_bound` use six decimal places; `reserved_upper_bound` is
  the exact ceiling of the raw upper bound to currency cents, never a
  nearest-cent or downward rounding. `run_cap` is in cents. This contract
  cannot prove the raw estimate is conservative: runtime W10/W13 must derive
  its upper bound from per-call token/tool limits and reserve before calls.
  It is an estimate, **not** a provider-call grant,
  ledger reservation, tenant budget or live price assertion. The zero-cost
  fixture proves no-spend testing only.

All validators return defensive copies and raise `PolicyPackageError` with a
stable code and bounded field path; they do not echo input values or exceptions
from providers. Unknown versions and oversized payloads fail closed.
`validate_package_bundle_v1` checks cross-record IDs, obligation, evidence and
source-unit links without Markdown parsing.

## Deferred gates

W04/W05 establish source rights and licensed corpus versions; W08 establishes
real applicability and full-instrument inventory completeness; W09 establishes
provenance/citation validity; W10/W13 own reservations, metering and tenant
budgets; W12/W16 own exact revision validation and human approval. This W06
validator cannot determine whether a cited source is legally applicable,
licensed, fresh, or factually accurate. Do not render or publish a package as
approved on the strength of schema validity alone.
