# Validator Coordinator Prompt

Your job is to emulate the current validator loop at decision level.

Read first:
- `validator-agent/app/agents/roles/coordinator.py`
- `validator-agent/app/agents/roles/evaluator.py`
- `validator-agent/app/services/logic.py`

Rules:
- final status must be one of `accepted`, `review`, `rejected`
- `reasons` must be a list
- `recommendations` must be a list
- if the draft is usable but needs changes, prefer `review`
- if major controls, references, or consistency are missing, use `rejected`

Return:
- `status`
- `reasons`
- `recommendations`
- brief parity note describing how close this looks to the legacy decision path
