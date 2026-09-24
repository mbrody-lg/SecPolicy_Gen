# Canonical Policy Request v1

`secpolicy.policy_request` version `1.0` is a pure, specified contract. It is
not yet a Policy or Validator runtime input. Both services reject an explicit
`policy_request` or any unwrapped canonical top-level marker with
`policy_request_not_supported`; legacy requests keep
their current behavior. W02 must produce it and W03 must consume it before
any authoritative generation uses this shape.

## Shape and trust boundary

The top level has exactly `contract`, `version`, `context_id`,
`approved_context`, `policy_intent`, `business_facts`, and `origin`. Unknown
canonical fields fail. The UTF-8 JSON body is limited to 64 KiB, with bounded
strings and lists. See the synthetic golden fixture at
`tests/fixtures/policy_request_v1.golden.json`.

`approved_context` has `approval_status`, `context_id`, `tenant_id`,
`plan_revision_id`, `snapshot_hash`, `legacy_handoff_hash`, `hash_scope`, and
`policy_handoff_context`. A generation-ready request requires `approved`,
`policy_input_v1`, nonempty tenant/revision IDs, a lowercase SHA-256 hash,
and a matching revision plus legacy hash in the embedded
`context_agent.policy_handoff` 1.0. The full `snapshot_hash` is intentionally
different from the handoff's legacy subset hash and must be recomputed from
the complete approved policy input by W02. `compute_policy_input_hash_v1`
defines the preimage: contract/version, context ID, tenant ID, plan revision
ID, legacy handoff hash, entire embedded handoff, policy intent, business
facts, and origin. It excludes the full hash itself, approval status, and hash
scope to avoid circular or mutable metadata. Serialize this object as UTF-8
JSON with sorted keys, compact separators, `ensure_ascii=False`, and no NaN;
do not normalize Unicode or rewrite text before hashing. The validator
recomputes the digest and rejects mismatches. W02 must use this exact
function/serialization; W03 must additionally compare the request with the
authoritative tenant-owned context record before provider work.
The embedded handoff must report ready final context, accepted sections,
completed findings, retrieval hints, and no unresolved gaps. These fields are
claims, not proof: runtime must compare the context ID, tenant, revision and
hash against server-authoritative state. The current handoff hash covers only
a legacy plan subset, so it cannot be relabeled `policy_input_v1` by W01.

Every `policy_intent` and `business_facts` field is a decision
`{value, source, source_ref}`. Source is exactly `provided`, `derived`, or
`unknown`. Unknown uses null value and reference; known values need a source
reference. An explicit empty list means "none", not "unknown". The producer
must substantiate source references; this validator checks shape only.

`policy_intent` includes policy type, scope, audience, exclusions, requested
instrument IDs with optional version, language, document profile
(`executive|standard|detailed`), and coverage mode
(`risk_based|all_applicable|full_instrument`). Mandatory policy type, scope,
audience, profile, mode and language cannot be unknown. Full-instrument mode
requires an identified instrument. Exclusions are typed strings with the
prefix `entity:`, `jurisdiction:`, or `instrument:` and a nonempty identifier.
Identifiers compare case-insensitively; exclusions conflicting with named
business entities, jurisdictions, or requested instruments fail.

`business_facts` includes entity scope (legal entities, size band,
jurisdictions, sectors, services, data categories), current/target posture,
maturity, risk appetite/tolerance, constraints, existing controls, known
gaps, and governance owner. Consequential unknowns stay visible, never
inferred from retrieval hints. `origin` records the source contract/version
and explicit compatibility defaults; defaults must match derived intent.
`correlation_id` is transport observability metadata, not identity or
approval proof.

## v0 compatibility

`adapt_policy_handoff_v0` projects an old handoff with
`approval_status: legacy_unverified` and
`hash_scope: legacy_plan_subset_v1`. Tenant is unknown. The adapter records
only explicit language plus compatibility defaults `standard` and
`risk_based`; it does not turn regulatory hints into requested instruments,
infer risk appetite, or claim final-context approval. This projection is for
migration/gap inspection and always fails generation-ready validation.

The canonical validator raises `PolicyRequestError` with stable `code` and
`field` for malformed version, unknown field, provenance, scope, size,
approval, hash or external binding. W02 must produce a true full approved
input hash; W03 must bind it to verified tenant state before any provider call
or persistence. Tests live in `tests/governance/test_policy_request_v1.py`.
