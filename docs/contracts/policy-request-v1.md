# Canonical Policy Request v1

`secpolicy.policy_request` versions `1.0` and `1.1` are pure, specified
contracts. They are not yet Policy or Validator runtime inputs. Both services
reject an explicit
`policy_request` or any unwrapped canonical top-level marker with
`policy_request_not_supported`; legacy requests keep
their current behavior. W02 must produce it and W03 must consume it before
any authoritative generation uses this shape.

## Shape and trust boundary

The top level has exactly `contract`, `version`, `context_id`,
`approved_context`, `policy_intent`, `business_facts`, and `origin`. Unknown
canonical fields fail. The UTF-8 JSON body is limited to 64 KiB, with bounded
strings and lists. See the synthetic golden fixture at
`tests/fixtures/policy_request_v1.golden.json` and
`tests/fixtures/policy_request_v1_1.golden.json`.

`approved_context` has `approval_status`, `context_id`, `tenant_id`,
`plan_revision_id`, `snapshot_hash`, `legacy_handoff_hash`, `hash_scope`, and
`policy_handoff_context`. A generation-ready request requires `approved`,
the version-matched hash scope (`policy_input_v1` or
`policy_input_v1_1`), nonempty tenant/revision IDs, a lowercase SHA-256 hash,
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
recomputes the digest and rejects mismatches. W02 must use the version-matched
function with this exact serialization. W03 must additionally compare the
request with the authoritative tenant-owned context record before provider work.
The embedded handoff must report ready final context, accepted sections,
completed findings, retrieval hints, and no unresolved gaps. These fields are
claims, not proof: runtime must compare the context ID, tenant, revision and
hash against server-authoritative state. The current handoff hash covers only
a legacy plan subset, so it cannot be relabeled `policy_input_v1` by W01.

Every `policy_intent` field and every 1.0 `business_facts` field is a decision
`{value, source, source_ref}`. Source is exactly `provided`, `derived`, or
`unknown`. Unknown uses null value and reference; known values need a source
reference. An explicit empty list means "none", not "unknown". The producer
must substantiate source references; this validator checks shape only. In 1.1,
the six `entity_scope` subfields are independent decisions instead. All 1.1
decisions add a mandatory `confidence` field.

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

## Version 1.1 fact provenance

Version `1.1` retains the top-level, intent, approval, handoff and origin
shapes, but changes `business_facts.entity_scope` from one decision wrapping
an object to an object containing **six independent decisions**:
`legal_entities`, `size_band`, `jurisdictions`, `sectors`, `services`, and
`data_categories`. Each has exactly `value`, `source`, `source_ref`, and
`confidence`. The same four-field shape is required for **every** 1.1
`policy_intent` decision and every other 1.1 `business_facts` decision.
The five list values accept a confirmed empty list; `size_band` is a nonempty
string when known. For every subfield, `unknown` requires null value and null
reference; `provided` or `derived` requires a nonempty reference and a valid
value. Case-insensitive duplicates in known scope lists fail. In addition,
`business_facts.business_priorities` and `critical_processes` are required
list-valued decisions with the same unknown/known rules. These are business
facts, not regulatory conclusions. All other 1.0 business decisions remain
required. Typed exclusions conflicting with a known legal entity or
jurisdiction fail; unknown scope subfields cannot establish absence of a
conflict, so W02 must ask material questions before claiming complete
applicability. The validator checks provenance *shape*, not whether a
`source_ref` resolves to an approved answer.

`confidence` is a bounded qualitative status: `confirmed`, `qualified`, or
`unknown`. An `unknown` source requires `unknown` confidence, and a
`provided` or `derived` source requires `confirmed` or `qualified` confidence;
other pairings fail. `confirmed` means the producer claims the fact is
substantiated against a reviewed source/answer; `qualified` means a source is
identified but a material caveat remains. Neither label is a numeric
probability, model self-score, regulatory assurance, or expert approval. This
pure validator checks only the enum and source/confidence consistency. W02
must define evidence and review criteria for assigning these labels, resolve
`source_ref` against the approved tenant-owned revision, preserve caveats, and
re-ask material questions rather than upgrading an inference to `confirmed`
without support. The embedded handoff fixture is also checked against the
actual Context Agent handoff validator in the 1.1 governance suite.

Version `1.1` requires `approved_context.hash_scope: policy_input_v1_1`.
`compute_policy_input_hash_v1_1` uses the same canonical serialization and
preimage field selection as 1.0; the version and entire new fact shape are
inside that preimage. Thus any changed decision value, source, reference, or
confidence changes the digest. The 1.0 fixture, `policy_input_v1` hash, validator and
legacy adapter remain unchanged. The validators are deliberately
version-specific: a 1.1 request cannot be silently down-converted to 1.0,
and neither version is accepted by service ingress yet. This is an explicit
compatibility break in the *offline contract*, not a runtime migration.

W02 must persist and approve the exact 1.1 input revision, substantiate every
`source_ref`, check conflicts and material unknowns against authoritative
tenant-owned answers, and recompute the digest before handoff. The shared
`contracts/` module is outside the current Context Agent Docker build context;
packaging/distribution belongs to W02 and is intentionally not changed here.

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
or persistence. Tests live in `tests/governance/test_policy_request_v1.py`
and `tests/governance/test_policy_request_v1_1.py`.
