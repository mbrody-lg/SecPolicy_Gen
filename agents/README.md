# Docker Agent scaffold for Phase 1

This directory contains the first tracked scaffold for the `SecPolicy_Gen` migration to Docker Agent (formerly `cagent` in older Docker Desktop versions).

## Files

- `secpolicy_team.yaml`: root agent plus the three Phase 1 specialists
- `prompts/`: role prompts kept separate so the team behavior can evolve without changing the migration map

## Scope

This scaffold is intentionally limited to Phase 1:

- reproduce the current flow conceptually
- enable dry runs and contract-oriented exploration
- avoid any production cutover or runtime replacement

## Expected usage

Use the helper script:

```bash
./scripts/run_cagent_phase1.sh
./scripts/run_cagent_phase1.sh --dry-run --exec
./scripts/run_cagent_phase1.sh --env-from-file .env.cagent --dry-run --exec
```

Or run the config directly with Docker Agent:

```bash
docker agent run agents/secpolicy_team.yaml
```

If your installation still exposes the legacy naming, `cagent run agents/secpolicy_team.yaml` should be equivalent on older setups.
