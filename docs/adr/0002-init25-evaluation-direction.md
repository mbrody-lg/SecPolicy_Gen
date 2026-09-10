# ADR 0002: INIT-25 Evaluation Direction

- Status: Accepted
- Date: 2026-07-16
- Initiative: INIT-25
- Decision: Pause at the runtime boundary

## Evidence

PRs #116-#121 establish the target boundary, runtime pin, non-authoritative
candidate ports, and independent admission, semantic, and operational gates.
The admission gate currently fails closed because verified service identity,
deadline cancellation, allowlisted service networking, and the two-capability
runtime topology are not observable. Consequently no live paired campaign has
been executed and semantic or operational readiness has not been established.

## Decision

Keep INIT-25 open but pause runtime expansion. Do not add a campaign runner,
publish a cutover claim, or relax the candidate ports. Resume the bounded
Policy-Validator pilot only after INIT-11 supplies verified principal,
audience, scope, and tenant binding; deadlines cancel provider work; and the
pinned Docker Agent runtime can call only the two allowlisted internal tools.

The decision rule is executable with `scripts/decide_init25_direction.py` once
its digest-linked admission, semantic, independent adjudication, operational,
and coordination reports exist. The current `pause` follows from those reports
being absent or blocked; it is not presented as a completed campaign artifact.
`continue` requires every independent gate and never authorizes cutover by
itself.

## Asset Disposition

- Keep PRs #109-#112 as contract-test foundations.
- Keep PR #113 as experimental configuration only.
- Keep PR #114 for bounded evidence semantics, not semantic proof.
- Keep PR #115 as a fail-closed compatibility adapter, not target topology.
- Keep PRs #118-#121 as candidate and evaluation gates.
- Supersede PRs #16-#17 and four-leaf Python CLI sequencing as migration
  direction.
- Remove no asset until the stacked evaluation PRs have been reviewed and the
  retained contract tests protect its behavior.

## Reassessment Trigger

Reassess when all admission evidence artifacts are digest-verified. A partial
campaign may yield `narrow`; only all independent gates may yield `continue`.
The initiative remains open in every outcome for later review.
