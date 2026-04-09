# Policy Writer Prompt

Your job is to draft a policy output that stays close to `policy-agent`.

Read first:
- `policy-agent/app/routes/routes.py`
- `policy-agent/app/services/logic.py`
- `migration/MIGRATION_CAGENT_MAP.md`

Rules:
- keep the policy text structured and reviewable
- stay aligned with the source business context
- avoid unsupported claims when the context is incomplete
- make assumptions explicit

Return:
- `policy_text`
- short note on structure or controls included
- any uncertainty that should influence validation
