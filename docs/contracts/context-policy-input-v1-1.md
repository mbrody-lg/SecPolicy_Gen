# Context-owned Policy Input 1.1 (W02)

This opt-in slice collects explicit policy intent and enterprise facts without
changing the legacy Context-to-Policy handoff. It does not enable Policy Agent
ingress or generation for `PolicyRequest 1.1`. Existing contexts with no
`policy_input` continue through v0, including the Docker functional smoke.

## API and authority

Authenticated, tenant-scoped Context routes:

- `GET /context/<context_id>/policy-input` returns the current revision,
  structured answers, deterministic material questions, and only the current
  approved request. `generation_available` is always false in W02.
- `POST /context/<context_id>/policy-input/answers` accepts exactly
  `{ "expected_revision": 0, "answers": { "policy_intent.policy_type":
  {"value": "access control", "confidence": "confirmed"} } }` on first use.
  Subsequent requests supply the current revision. Each field is typed,
  bounded and allowlisted. An answer can be removed with a JSON `null` patch.
  Sending this route is an explicit 1.1 opt-in; it does not reuse legacy
  free-text exclusions or infer regulatory obligations. `confidence` must be
  a string (`confirmed` or `qualified`); arrays/objects return `400` without
  writing a revision.
- `POST /context/<context_id>/policy-input/approve` accepts exactly
  `{ "expected_revision": 1 }`. It requires all material answers confirmed,
  an approved current Context plan, a ready final Context handoff, and a
  successful canonical `validate_policy_request_v1_1` call. Concurrent
  answer, plan or final-context edits fail the tenant-bound CAS update.
  Approval also reconciles directly comparable Context facts: the handoff
  country must be among explicit jurisdictions, its sector among explicit
  sectors, and its data types among explicit data categories when supplied.
  A conflict returns `409` and requires correcting/reconfirming the Context
  and answer snapshots, not a silent override. Free-text semantic equivalence
  is not inferred.

The Context document owns `policy_input`: current answer map, append-only
answer revisions, current approval and approval history. Every `source_ref`
names `answer:<field>@revision:<n>`; a request is constructed only if the
latest recorded revision contains exactly the current answers. An approval
stores its answer snapshot and the full validated request with
`policy_input_v1_1` hash. Later edits create a new answer revision and clear
current approval, while keeping the old decision for audit. A changed plan,
final handoff, security context or tenant also makes the prior approval
ineffective when checked. Approval of the legacy Context *plan* alone never
approves policy input.

Only fields affecting scope, presentation, coverage or action selection are
mandatory questions. Unknown optional facts remain `source=unknown`, never
`provided`. `full_instrument` additionally requires a confirmed, versioned
instrument and confirmed entity, jurisdiction, sector, service and
data-category scope. Typed exclusions cannot
contradict included entities, jurisdictions or requested instruments. This is
an input-quality gate, not a decision about legal applicability or source
rights.

## Packaging and rollout

Context Docker uses an additional build context restricted to repository
`contracts/` and copies that one canonical validator to `/shared/contracts`.
The live source bind mount remains `/context-agent`; `PYTHONPATH=/shared`
keeps the contract importable. Snyk's direct Context image build passes the
same named context. This avoids a repository-root build context that could
send ignored local secrets or corpora to Docker.

Until W03 enables validated 1.1 ingestion in Policy Agent, both the HTTP
generation route and background worker reject an opted-in context. An
approved 1.1 request is inspectable but not delivered downstream. Legacy
contexts have no new mandatory question gate. W04/W05 still govern source
rights; no real corpus or paid provider is used by this slice.
