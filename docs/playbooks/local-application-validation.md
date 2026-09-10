# Local Application Validation

Use this playbook to install and test SecPolicyGen from the repository root.
It is the canonical local validation path; service playbooks contain only
service-specific checks.

## Choose The Validation Level

| Goal | Command | Provider and RAG | Data impact |
|---|---|---|---|
| Exercise the UI states | `make context-browser-smoke` | Deterministic fixtures | Adds browser fixtures to a test organization |
| Prove OIDC interoperability | `make local-oidc-smoke` | Local Keycloak | Recreates Context Agent and identity, then leaves the HTTPS test profile active |
| Prove the application loop | `make functional-smoke` | Mock agents | Removes Compose volumes on completion |
| Run the critical application path | `make critical-path-validation` | Unit, evaluation, browser, governance, and mock loop | Stops the local stack and removes Compose volumes during smoke cleanup |
| Prove real providers with an existing RAG backup | `make functional-smoke-real-backup` | Real YAML and restored Chroma | Replaces Chroma data and removes Compose volumes on completion |
| Rebuild and prove real RAG | `make functional-smoke-real-full` | Real YAML and source indexing | Reindexes RAG and removes Compose volumes on completion |

Use the manual path below for exploratory testing. Use the automated levels for
repeatable regression evidence.

## 1. Prepare The Environment

Prerequisites:

- Docker with Compose support
- Git, `make`, `curl`, `openssl`, and Python 3
- pnpm only for host-side frontend checks
- enough Docker storage for the application images and embedding model
- a real provider API key only when testing real model calls

Create the ignored runtime environment from the tracked contract:

```bash
test -f infrastructure/.env || cp infrastructure/.env.example infrastructure/.env
make docker-preflight
```

Keep the fake local OIDC, Flask, callback, and Grafana values for local
development. Replace `OPENAI_API_KEY` and other selected provider credentials
only when real generation is required. Never commit `infrastructure/.env`.

The active YAML files select models, token limits, and agent behavior.
Environment variables provide credentials and runtime wiring; they do not
replace the YAML model contract. Choose one Context Agent mode before startup:

- deterministic/manual UI: set `CONTEXT_CONFIG_PATH` in `infrastructure/.env`
  to `/context-agent/app/config/examples/context_agent.example.mock.yaml`
- real generation: keep `/context-agent/app/config/context_agent.yaml` and
  provide the selected provider credential

The fake API keys in `.env.example` are placeholders; they cannot execute real
context or policy generation.

## 2. Resolve The Local Identity Host

The disposable identity provider uses `identity.test`. Ensure the host resolves
to loopback:

```text
127.0.0.1 identity.test
```

On macOS or Linux, add that entry to `/etc/hosts` with administrator approval if
it is not already present. After starting the stack, verify discovery without
sending credentials:

```bash
curl -fsS \
  http://identity.test:8080/realms/secpolicygen/.well-known/openid-configuration \
  >/dev/null
```

## 3. Start The Application

Start all services and the optional local OIDC provider:

```bash
make local-oidc-up
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Wait until MongoDB, Context Agent, Policy Agent, Validator Agent, Grafana,
Prometheus, and the identity provider report healthy. Chroma, Loki, Alloy, and
the HTTPS edge must be running even where no container healthcheck is defined.

Verify application readiness:

```bash
curl -fsS http://localhost:5003/ready
curl -fsS http://localhost:5002/ready
curl -fsS http://localhost:5001/ready
```

`/health` proves that a process is alive. `/ready` proves that its required
configuration and dependencies are available.

## 4. Provision The Local User

The identity provider authenticates the user; SecPolicyGen owns application
membership and permissions. Provision the fixed local subject once, or rerun the
idempotent command after cleaning MongoDB:

```bash
docker exec context_agent_web python manage_identity.py \
  --issuer http://identity.test:8080/realms/secpolicygen \
  --subject 11111111-1111-1111-1111-111111111111 \
  --organization-id local-development \
  --organization-name "SecPolicyGen Local Organization" \
  --role admin
```

Open [http://localhost:5003](http://localhost:5003) and sign in with the local-only
fixture:

```text
Username: developer
Password: fake-local-developer-password
```

Expected result: the dashboard displays `Generated contexts` and the active
organization `SecPolicyGen Local Organization`.

## 5. Prepare RAG

Validate the source manifest and Chroma connection, then inspect runtime status:

```bash
make policy-rag-validate
curl -sS http://localhost:5002/rag/status
```

On a new installation, `requires_refresh` and HTTP `503` are expected before RAG
bootstrap. After bootstrap, require `status: ready`, all collections configured
by `policy-agent/app/config/rag_sources.yaml`, no missing collections, and its
pinned embedding model.

For backup compatibility evidence, set `RAG_VALIDATE_CHROMA=true` in
`infrastructure/.env`, recreate Policy Agent, and repeat `/rag/status`. Require
every `collection_checks` entry to report `ready`; this performs the opt-in deep
embedding query instead of checking only collection names and cache presence.

Choose one bootstrap path.

### Restore A Compatible Backup

```bash
CHROMA_BACKUP_FILE=/absolute/path/rag-runtime.tar.gz make policy-rag-restore
```

Restore replaces the current Chroma volume contents. The backup must have been
built with the same collection names, embedding model, and revision. Create a
new local backup later with:

```bash
CHROMA_BACKUP_FILE=/absolute/path/rag-runtime.tar.gz make policy-rag-backup
```

The Chroma backup does not contain the embedding-model cache.

If `/rag/status` reports the restored collections but marks the model as
`not_cached`, preload only the model pinned by the manifest without reindexing:

```bash
docker exec -e POLICY_AGENT_ALLOW_MODEL_DOWNLOAD=1 \
  policy_agent_service python -c \
  'from app.rag.sources import load_rag_source_manifest; from app.agents.vector.model_loader import download_model_if_needed; defaults = load_rag_source_manifest()["embedding_defaults"]; download_model_if_needed(defaults["model"], revision=defaults.get("revision"))'
```

Repeat `/rag/status` and require the model and RAG status to be `ready`.
Prove that the pinned revision can load without network access:

```bash
docker exec -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  policy_agent_service python -c \
  'from app.rag.sources import load_rag_source_manifest; from app.agents.vector.model_loader import load_model; defaults = load_rag_source_manifest()["embedding_defaults"]; load_model(defaults["model"], revision=defaults.get("revision")); print("Embedding model loaded")'
```

### Initialize Empty Chroma From Source Documents

Set `POLICY_AGENT_ALLOW_MODEL_DOWNLOAD=1` in `infrastructure/.env`, recreate
Policy Agent, and index the tracked source corpus:

```bash
make rebuild
make policy-vectorize
```

After the first successful download, restore
`POLICY_AGENT_ALLOW_MODEL_DOWNLOAD=0` and recreate the service. The model remains
in the persistent Docker cache. Indexing can require more than 1 GB of temporary
storage and take many minutes.

`make policy-vectorize` initializes or adds to the current collections; it is not
a guaranteed clean rebuild. To replace existing collections, use the controlled
RAG refresh from Operational Status or `POST /rag/refresh`, then follow the
asynchronous job in `/rag/status`. Refresh deletes and rebuilds the selected
collections, so create a backup first when the current index matters.

Repeat the status check after either path. Do not continue to real policy
generation while `/rag/status` reports `requires_refresh`.

## 6. Load Example Contexts When Needed

To populate the manual local organization with the tracked example answers:

```bash
docker exec -e CONTEXT_IMPORT_ORGANIZATION_ID=local-development \
  context_agent_web python generate_context_from_yaml.py \
  /context-agent/app/config/examples/answers
```

This command deletes existing contexts and interactions for `local-development`
before importing the fixtures. Add `--auto-approve-plan` only when the test must
skip manual plan approval. Treat any `Error with <fixture>` output as a failed
import even if the command exits successfully, and verify that all expected
contexts appear in the dashboard before continuing.

## 7. Test The Workflow Manually

1. Select `New context` and answer the initial security questionnaire.
2. Submit `Generate context`; confirm the new case appears on the dashboard.
3. In `Intake`, answer pending or task-discovered questions and use `Add context`
   for relevant free-form information.
4. In `Context Building`, review the Security Context analysis. Use `Update
   context` until no required information remains.
5. In `Planning`, inspect scope, tasks, expected findings, and any new questions.
   Approve only when the plan reflects the company and its risk posture.
6. Select `Execute approved plan`. In `Execution`, confirm progress changes while
   the asynchronous job runs and that every completed task retains its findings.
7. In `Final Context`, verify that findings are structured and complete. Add
   section comments where detail is missing, regenerate those sections, and run
   `Synthesize final context`.
8. Confirm Context Workplace is complete before entering Policy Workplace.
   `Generate and validate` must remain unavailable while Final Context is not
   ready.
9. For a real end-to-end run, generate the policy and follow progress through
   Policy Workplace and Validator Workplace until a validated policy is stored.

At every asynchronous step, the current task, completed task count, and failure
state must remain visible after refreshing the page.

## 8. Run Regression Gates

Run the focused UI gate while preserving the running stack:

```bash
make context-browser-smoke
```

Run the full deterministic critical path only when local Compose volumes can be
discarded:

```bash
make critical-path-validation
```

For real provider and RAG evidence, choose exactly one real smoke command from
the validation table. Evidence is written under `migration/`. After
`make local-oidc-smoke`, rerun `make local-oidc-up` before returning to the manual
HTTP workflow.

## 9. Diagnose A Failure

1. Open Operational Status in the application navigation.
2. Check `/ready` for the affected service.
3. Capture the response `X-Correlation-ID` or the correlation id shown by the UI.
4. Open `GET /diagnostics/<correlation-id>` from the authenticated administrator
   session; anonymous `curl` requests are rejected.
5. Run `make logs` and filter by that correlation id or context id.
6. Use Grafana at [http://localhost:3000](http://localhost:3000) for logs, metrics,
   and service-level trends.

For symptom-specific recovery, use [Developer Recovery](./developer-recovery.md).
For the cross-service observability contract, use the
[Context -> Policy -> Validator Runbook](./context-policy-validator-loop.md).

## 10. Stop Or Reset

Preserve local MongoDB, Chroma, and model caches and stop the OIDC overlay:

```bash
make local-oidc-down
```

Use `make down` for the base stack without the local OIDC overlay.

Delete Compose volumes and all local application data:

```bash
make clean
```

Back up valuable MongoDB and Chroma data before `make clean`, real smoke runs, or
any migration test.
