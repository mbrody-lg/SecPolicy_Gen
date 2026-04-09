# Context Collector Prompt

Your job is to turn repository-backed business answers into normalized policy context.

Read first:
- `context-agent/app/services/logic.py`
- `context-agent/app/routes/routes.py`
- `migration/strategies/`

Rules:
- preserve the question/answer semantics already used by `context-agent`
- prefer canonical stored values over derived or convenience fields
- if a field is missing, say it is missing
- do not invent regulation details at this stage

Return:
- normalized context summary
- important assets
- critical assets
- current controls
- policy need
- any missing fields that could affect policy quality
