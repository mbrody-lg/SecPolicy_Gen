# Developer Recovery Playbook

Use this playbook when the local Docker stack is unhealthy, stale, blocked by
ports, or failing before the Context -> Policy -> Validator smoke path can run.

This guide documents recovery actions only. It does not change Makefile,
Compose, or script behavior.

## Current Service Ports

| Service | Host URL | Container |
|---------|----------|-----------|
| Context Agent | `http://localhost:5003` | `context_agent_web` |
| Policy Agent | `http://localhost:5002` | `policy_agent_service` |
| Validator Agent | `http://localhost:5001` | `validator_agent_service` |
| Chroma | `http://localhost:8000` | Compose service `chroma` |
| MongoDB | `localhost:27017` | `context_mongo` |

## Normal Recovery Ladder

Start with the least destructive action that can produce useful evidence:

1. Confirm Docker is available:

   ```bash
   docker ps
   ```

2. Start or refresh the stack:

   ```bash
   make up
   ```

3. Check the three readiness endpoints:

   ```bash
   curl -fsS http://localhost:5003/ready
   curl -fsS http://localhost:5002/ready
   curl -fsS http://localhost:5001/ready
   ```

4. Run the smoke path when readiness is green:

   ```bash
   make functional-smoke
   ```

5. Use the full evidence command when the change crosses service boundaries:

   ```bash
   make critical-path-validation
   ```

6. Stop the stack when finished:

   ```bash
   make down
   ```

## Recovery Cases

### Docker Daemon Stopped

Symptom:
- `docker ps` or `make up` cannot connect to the Docker daemon.

First diagnostic:

```bash
docker ps
```

Safe action:
- Start Docker Desktop or the local Docker service, then rerun `docker ps`.

Expected evidence:
- `docker ps` returns a table instead of a daemon connection error.
- `make up` can start or rebuild the Compose stack.

### Port Collision

Symptom:
- `make up` reports that `5003`, `5002`, `5001`, `8000`, or `27017` is already
  allocated.

First diagnostic:

```bash
lsof -nP -iTCP:5003 -sTCP:LISTEN
lsof -nP -iTCP:5002 -sTCP:LISTEN
lsof -nP -iTCP:5001 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:27017 -sTCP:LISTEN
```

Safe action:
- Stop the unrelated local process if it is yours, or stop the existing stack
  with `make down` if the listener is from this project.

Expected evidence:
- The conflicting port no longer appears in `lsof`.
- `make up` completes and each service answers `/ready`.

### Service Unhealthy

Symptom:
- Compose marks an agent unhealthy, or smoke preflight reports a readiness
  failure.

First diagnostic:

```bash
curl -fsS http://localhost:5003/ready
curl -fsS http://localhost:5002/ready
curl -fsS http://localhost:5001/ready
make logs
```

Safe action:
- Read `/ready` before `/health`; readiness is the operational gate.
- Use `make logs` to identify the failing dependency or config field.
- If the container was built before recent local changes, run `make rebuild`.

Expected evidence:
- The failing `/ready` endpoint returns `200`.
- `migration/functional-smoke-result.json` has no `preflight_failures` after
  `make functional-smoke`.

### Mongo Or Chroma Not Ready

Symptom:
- Agents are alive but `/ready` returns `503`.
- Policy generation or RAG setup fails while Chroma is still starting.

First diagnostic:

```bash
make logs
curl -fsS http://localhost:5002/ready
```

Safe action:
- Wait for Compose healthchecks to settle, then rerun readiness checks.
- If startup stays stuck after a rebuild, run `make down` followed by `make up`.

Expected evidence:
- `policy-agent` readiness returns `200`.
- Smoke evidence shows no Chroma or Mongo preflight failure.

### Stale Image Or Container

Symptom:
- Logs or behavior do not match the current working tree.
- A dependency appears missing inside a container after code or dependency
  changes.

First diagnostic:

```bash
make logs
```

Safe action:

```bash
make rebuild
```

Expected evidence:
- The rebuilt service starts cleanly.
- The relevant service test target passes, such as `make policy-tests`,
  `make validator-tests`, or `make context-tests`.

### Missing Config

Symptom:
- `/ready` reports missing runtime configuration.
- `make up` starts containers but service tests or smoke fail immediately.

First diagnostic:

```bash
make logs
curl -fsS http://localhost:5003/ready
curl -fsS http://localhost:5002/ready
curl -fsS http://localhost:5001/ready
```

Safe action:
- Restore the expected local `infrastructure/.env` values from the project
  setup path.
- Do not paste secrets into logs, PR descriptions, or issue comments.

Expected evidence:
- Readiness returns `200` for the affected service.
- Logs identify configuration presence without exposing secret values.

### RAG Index Drift

Symptom:
- The stack is ready, but policy generation fails to retrieve expected context
  or Chroma-backed behavior differs from the expected local state.

First diagnostic:

```bash
docker exec policy_agent_service python scripts/index_pdfs_to_chroma.py --validate-only
```

Safe action:
- Prefer validate-only checks before reindexing.
- Reindex only when the changed work requires the local Chroma collection to be
  refreshed.

Expected evidence:
- Validate-only output confirms the expected collection state, or identifies
  the collection that needs reindexing.

### Stale Volumes

Symptom:
- Rebuilds do not clear persistent Mongo or Chroma state problems.
- Recovery is blocked by old data rather than the current code.

First diagnostic:

```bash
make logs
```

Safe action:
- Export or preserve any local data you still need.
- Prefer targeted diagnosis before deleting volumes.

Optional destructive action:

```bash
make clean
make up
```

Warning:
- `make clean` removes Compose volumes, including `mongo_data` and
  `chroma_data`. This can delete local database state and local RAG indexes.

Expected evidence:
- The rebuilt stack reaches readiness from a clean state.
- Any RAG collections required for the workflow are revalidated or rebuilt.

## Evidence To Keep

- Command that failed and command that recovered the stack.
- `/ready` output for the affected service.
- Relevant `make logs` excerpt with secrets redacted.
- `migration/functional-smoke-result.json` after smoke recovery.
- Correlation id and diagnostics lookup when the failure occurred inside the
  Context -> Policy -> Validator loop.
