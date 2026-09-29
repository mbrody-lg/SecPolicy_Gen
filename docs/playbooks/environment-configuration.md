# Environment Configuration Contract

Use this contract when changing environment variables, example env files,
Compose wiring, provider clients, or CI secret handoff. It is the INIT-02
source of truth for local, Docker, and future CI configuration.

This document classifies configuration. It does not grant permission to commit
real secrets, add service-to-service authentication, or implement CI workflows.

## Classification

| Class | Meaning | Rule |
|-------|---------|------|
| `secret` | Credential or signing material | Must be supplied by environment or secret manager; never log or commit real values |
| `fake local` | Placeholder that looks intentionally non-production | Allowed in examples and deterministic local smoke only |
| `required` | Service cannot perform expected runtime work without it | Missing value must fail deterministically and safely |
| `safe default` | Non-secret local default with low risk | May default in code when documented |
| `runtime knob` | Operational tuning value | Must be typed, bounded, and safe when malformed |
| `legacy` | Historical or transitional variable | Do not introduce new dependencies; remove or document migration path |
| `future owner` | Belongs to another initiative | Document handoff; do not implement prematurely |

## Global Rules

- Real secrets must never be committed, pasted into PR descriptions, printed in
  tests, or exposed through HTTP responses, readiness payloads, diagnostics, or
  smoke artifacts.
- Example values must be fake and visibly local. Prefer placeholders such as
  `fake-local-openai-key` over values that resemble live provider keys.
- `TESTING=true` may use test-only placeholders. Non-testing runtime must not
  silently invent secrets.
- Config errors may name the missing or malformed variable, but must not include
  the raw value.
- `correlation_id` and `X-Correlation-ID` are observability metadata only. They
  are not authentication, authorization, or caller-origin proof.
- INIT-02 may document future CI and service-auth needs, but INIT-04 owns
  GitHub Actions implementation and INIT-11 owns service-to-service auth.

## Context Agent

| Variable | Class | Default policy | Used by | Validation expectation |
|----------|-------|----------------|---------|------------------------|
| `FLASK_SECRET_KEY` | `secret`, `required` | Required outside `TESTING`; fake local only in examples | Flask session signing | App init fails safely when missing outside tests |
| `OIDC_ISSUER_URL` | `required` | Required outside `TESTING` | Provider-neutral OIDC discovery | HTTPS outside localhost; no query or fragment |
| `OIDC_CLIENT_ID` | `required` | Required outside `TESTING` | OIDC relying-party identifier | Reject blank values |
| `OIDC_CLIENT_SECRET` | `secret`, `required` | Required outside `TESTING`; fake local only in examples | Confidential OIDC client authentication | Never expose through logs or responses |
| `OIDC_REDIRECT_URI` | `required` | Required outside `TESTING` | Exact OIDC callback URI | HTTPS outside localhost; register exact value at the provider |
| `OIDC_SCOPES` | `runtime knob` | `openid profile email` | Requested identity claims | Must contain `openid` |
| `POLICY_CALLBACK_TOKEN` | `secret`, `required` | Required outside `TESTING` | Policy Agent workload authentication for the Context Agent callback | Send only as `Authorization: Bearer`; rotate independently from browser/OIDC secrets |
| `WORKLOAD_CONTEXT_SIGNING_KID` | `required` | Required outside `TESTING` | Select Context signing key ID | Match the current `WORKLOAD_CONTEXT_VERIFY_KEYS` entry at receivers |
| `WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64` | `secret`, `required` | Required outside `TESTING`; deterministic seed only in test examples | Context-only Ed25519 signing seed | 32 raw bytes encoded as base64; never distribute to Policy/Validator |
| `CONTEXT_IMPORT_ORGANIZATION_ID` | `operation input` | Required by fixture import | Organization owning imported contexts | Must reference an active, locally provisioned organization |
| `TESTING` | `safe default` | Defaults to `false` | App factory/tests | Parse as explicit truthy flag |
| `DEBUG` | `runtime knob` | Defaults to `false` | App factory/log behavior | Example defaults to `false`; dev override only |
| `MONGO_URI` | `required` | Local Docker default may be documented | Flask-PyMongo | Missing/malformed handling should be deterministic |
| `POLICY_AGENT_URL` | `required` | Docker default `http://policy-agent:5000` | Context to policy handoff | Validate as service URL before use |
| `VALIDATOR_AGENT_URL` | `required` | Docker default `http://validator-agent:5000` | Context to validator handoff | Validate as service URL before use |
| `CONFIG_PATH` | `required` | Defaults to `app/config/context_agent.yaml` on host; Compose passes container path | Agent config loading | Path should be explicit in Docker |
| `QUESTIONS_CONFIG_PATH` | `required` | Defaults to `app/config/context_questions.yaml` on host; Compose passes container path | Question/prompt config loading | Path should be explicit in Docker |
| `OPENAI_API_KEY` | `secret` | No real example value | OpenAI client | Required only for non-mock provider execution |
| `OPENAI_API_URL` | `runtime knob` | Safe provider default may be documented | OpenAI client | Compose should pass explicitly when used |
| `OPENAI_STRUCTURED_API_MODE` | `runtime knob` | Safe default `chat_completions` | OpenAI structured provider adapter | Restrict to `chat_completions` or `responses`; default must preserve current behavior |
| `OPENAI_PROVIDER_TIMEOUT_SECONDS` | `runtime knob` | Safe default `180` | OpenAI SDK client | Parse as positive numeric value; errors must not expose provider payloads |
| `POLICY_AGENT_TIMEOUT_SECONDS` | `runtime knob` | Safe default `30` | Policy handoff HTTP calls | Parse as positive numeric value |
| `VALIDATOR_AGENT_TIMEOUT_SECONDS` | `runtime knob` | Safe default `30` | Validator handoff HTTP calls | Parse as positive numeric value |
| `PIPELINE_JOB_STALE_AFTER_SECONDS` | `runtime knob` | Safe default `1800` | Async policy pipeline job recovery | Parse as positive numeric value |
| `MAX_CONTENT_LENGTH` | `runtime knob` | Safe default `262144` | Flask request limits | Parse as positive integer |
| `SESSION_COOKIE_SECURE` | `runtime knob` | Local default `false`; non-local should be `true` | Flask session cookie | Parse as explicit truthy flag |
| `TRUSTED_HOSTS` | `runtime knob` | Optional local list | Flask host validation | Parse comma-separated host list |
| `CONTEXT_IMPORT_PATH` | `safe default` | Defaults to example answers path in container tooling | YAML fixture import | Host/tool-only unless imported in runtime |
| `CONTEXT_IMPORT_AUTO_APPROVE_PLAN` | `runtime knob` | Defaults to `false` | YAML fixture import | Parse as explicit truthy flag; must not execute task synthesis |

## Policy Agent

| Variable | Class | Default policy | Used by | Validation expectation |
|----------|-------|----------------|---------|------------------------|
| `FLASK_SECRET_KEY` | `secret`, `required` | Required outside `TESTING`; fake local only in examples | Flask session signing | App init fails safely when missing outside tests |
| `WORKLOAD_CONTEXT_VERIFY_KEYS` | `required` | Required outside `TESTING` | Verify Context Agent requests | Public Ed25519 key registry with `kid`, explicit `tenant_ids`, optional previous-key `accept_until`; no private seed |
| `WORKLOAD_VALIDATOR_VERIFY_KEYS` | `required` | Required outside `TESTING` | Verify Validator Agent policy updates | Distinct public key registry; no Validator private seed |
| `WORKLOAD_CANDIDATE_VERIFY_KEYS` | `required` | Required outside `TESTING` | Verify Docker Agent candidate generation | Candidate public key registry; bind each key to one tenant ID |
| `TESTING` | `safe default` | Defaults to `false` | App factory/tests | Parse as explicit truthy flag |
| `DEBUG` | `runtime knob` | Defaults to `false` | App factory/log behavior | Example defaults to `false`; dev override only |
| `MONGO_URI` | `required` | Local Docker default may be documented | Flask-PyMongo | Missing/malformed handling should be deterministic |
| `CONFIG_PATH` | `required` | Compose passes `/policy-agent/app/config/policy_agent.yaml` | Agent config loading | Path should be explicit in Docker |
| `OPENAI_API_KEY` | `secret` | No real example value | OpenAI client | Required only for non-mock provider execution |
| `OPENAI_API_URL` | `runtime knob` | Safe provider default may be documented | OpenAI client | Compose should pass explicitly when used |
| `CHROMA_HOST` | `required` | Docker default `chroma`; host default may differ | Chroma HTTP client/readiness | Missing/blank value should fail safely |
| `CHROMA_PORT` | `required` | Docker default `8000` | Chroma HTTP client/readiness | Parse as integer port from 1 to 65535 |
| `CHROMA_READINESS_MODE` | `runtime knob` | `config_only` outside live Docker checks; Compose may set `live` | Policy readiness | Reject unexpected modes |
| `RAG_SOURCES_PATH` | `required` | Compose passes `/policy-agent/app/config/rag_sources.yaml` | RAG source manifest | Manifest path must exist before indexing/validation |
| `RAG_VALIDATE_CHROMA` | `runtime knob` | Defaults to off | RAG status and validate-only script | Parse as explicit boolean flag; deep Chroma embedding probes must stay opt-in |
| `POLICY_AGENT_ALLOW_RAG_REFRESH` | `runtime knob` | Defaults to off | Controlled local RAG refresh route | Parse as explicit boolean flag |
| `POLICY_AGENT_RAG_REFRESH_TIMEOUT_SECONDS` | `runtime knob` | Safe Docker default `2400` | Controlled local RAG refresh command | Parse as positive numeric value; long enough for a full local reindex |
| `POLICY_AGENT_ALLOW_MODEL_DOWNLOAD` | `runtime knob` | Defaults to off | Embedding model loader/indexing | Must be explicit for one-time model download |
| `METADATA_SCHEMA_PATH` | `runtime knob` | Optional/local until governed | RAG metadata validation | Document if promoted to active contract |
| `MAX_CONTENT_LENGTH` | `runtime knob` | Safe default `262144` | Flask request limits | Parse as positive integer |
| `SESSION_COOKIE_SECURE` | `runtime knob` | Local default `false`; non-local should be `true` | Flask session cookie | Parse as explicit truthy flag |
| `TRUSTED_HOSTS` | `runtime knob` | Optional local list | Flask host validation | Parse comma-separated host list |
| `CHROMA_COLLECTIONS_PATH` | `legacy` | Do not add new uses | Historical RAG docs | Replace or document migration to `RAG_SOURCES_PATH` |

## Validator Agent

| Variable | Class | Default policy | Used by | Validation expectation |
|----------|-------|----------------|---------|------------------------|
| `FLASK_SECRET_KEY` | `secret`, `required` | Required outside `TESTING`; fake local only in examples | Flask session signing | App init fails safely when missing outside tests |
| `WORKLOAD_CONTEXT_VERIFY_KEYS` | `required` | Required outside `TESTING` | Verify Context Agent validation requests | Context public keys and explicit tenant allowlist only |
| `WORKLOAD_VALIDATOR_SIGNING_KID` | `required` | Required outside `TESTING` | Select Validator signing key ID | Match the current `WORKLOAD_VALIDATOR_VERIFY_KEYS` entry at Policy |
| `WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64` | `secret`, `required` | Required outside `TESTING`; deterministic seed only in test examples | Validator-only Ed25519 signing seed | 32 raw bytes encoded as base64; never distribute to Policy/Context |
| `WORKLOAD_CANDIDATE_VERIFY_KEYS` | `required` | Required outside `TESTING` | Verify Docker Agent candidate validation | Candidate public key registry; bind each key to one tenant ID |
| `TESTING` | `safe default` | Defaults to `false` | App factory/tests | Parse as explicit truthy flag |
| `DEBUG` | `runtime knob` | Defaults to `false` | App factory/log behavior | Example defaults to `false`; dev override only |
| `MONGO_URI` | `required` | Local Docker default may be documented | Flask-PyMongo | Missing/malformed handling should be deterministic |
| `CONFIG_PATH` | `required` | Compose passes `/validator-agent/app/config/validator_agent.yaml` | Agent config loading | Path should be explicit in Docker |
| `POLICY_AGENT_URL` | `required` | Docker default `http://policy-agent:5000` | Validator to policy update flow | Validate as service URL before use |
| `POLICY_AGENT_TIMEOUT_SECONDS` | `runtime knob` | Safe default `30` | Policy update HTTP calls | Parse as positive numeric value |
| `OPENAI_API_KEY` | `secret` | No real example value | OpenAI client | Required only for non-mock provider execution |
| `OPENAI_API_URL` | `runtime knob` | Safe provider default may be documented | OpenAI client | Compose should pass explicitly when used |
| `MISTRAL_API_KEY` | `secret` | No real example value | Mistral client | Required only for non-mock provider execution |
| `MISTRAL_API_URL` | `runtime knob` | Safe provider default `https://api.mistral.ai/v1` may be documented | Mistral client | Compose should pass explicitly when used |
| `MAX_CONTENT_LENGTH` | `runtime knob` | Safe default `262144` | Flask request limits | Parse as positive integer |
| `SESSION_COOKIE_SECURE` | `runtime knob` | Local default `false`; non-local should be `true` | Flask session cookie | Parse as explicit truthy flag |
| `TRUSTED_HOSTS` | `runtime knob` | Optional local list | Flask host validation | Parse comma-separated host list |

## Infrastructure And Tooling

| Variable | Class | Default policy | Used by | Validation expectation |
|----------|-------|----------------|---------|------------------------|
| `AGENT_CONFIG_DIR` | `safe default` | Defaults to `runtime/agent-config` on the host | Compose bind mounts and agent-config bootstrap/validation tooling | Directory must remain outside tracked service source and contain the expected YAML files |
| `CONTEXT_AGENT_CONFIG_PATH` | `safe default` | Defaults to `/agent-config/context_agent.yaml` in Compose | Context Agent `CONFIG_PATH` wiring | Mounted file must pass the Context Agent runtime loader |
| `CONTEXT_QUESTIONS_CONFIG_PATH` | `safe default` | Defaults to `/agent-config/context_questions.yaml` in Compose | Context Agent `QUESTIONS_CONFIG_PATH` wiring | Mounted file must pass the Context Agent questions loader |
| `POLICY_AGENT_CONFIG_PATH` | `safe default` | Defaults to `/agent-config/policy_agent.yaml` in Compose | Policy Agent `CONFIG_PATH` wiring | Mounted file must pass the Policy Agent runtime loader |
| `VALIDATOR_AGENT_CONFIG_PATH` | `safe default` | Defaults to `/agent-config/validator_agent.yaml` in Compose | Validator Agent `CONFIG_PATH` wiring | Mounted file must pass the Validator Agent runtime loader |
| `FLASK_ENV` | `runtime knob` | Local Compose uses `development` | Flask runtime | Document as local-only until production runtime exists |
| `FLASK_RUN_DEBUG` | `runtime knob` | Defaults to off; local override only | Flask development server | Must not be enabled by default |
| `FLASK_APP` | `safe default` | Dockerfiles set each service app module | Local/container Flask runner | Required only for `flask run` style execution |
| `PYTHONDONTWRITEBYTECODE` | `safe default` | Dockerfiles set `1` | Python container runtime | Build/runtime hygiene only |
| `PYTHONUNBUFFERED` | `safe default` | Dockerfiles set `1` | Python container logging | Keeps container logs unbuffered |
| `PYTHONPATH` | `safe default` | Dockerfiles set service root where imports need it | Container import resolution | Required for policy/validator container imports |
| `PIP_NO_CACHE_DIR` | `safe default` | Policy Dockerfile sets `1` | Container dependency install | Build hygiene only |
| `PYTHON_BIN` | `safe default` | Defaults to `python3` | Host bootstrap script | Must point to Python 3.11+ |
| `READINESS_TIMEOUT_SECONDS` | `runtime knob` | Safe default `120` | Critical-path script | Parse as positive integer |
| `READINESS_INTERVAL_SECONDS` | `runtime knob` | Safe default `2` | Critical-path script | Parse as positive integer |
| `LOG_TAIL_LINES` | `runtime knob` | Safe default `80` | Critical-path diagnostics | Keep logs bounded and redacted |
| `MIGRATION_SMOKE_MOCK` | `runtime knob` | Defaults to mock mode on | Functional smoke | Default smoke must not need real provider keys |
| `MIGRATION_SMOKE_CLEAN_DB` | `runtime knob` | Defaults to clean on | Functional smoke | Parse as explicit truthy flag |
| `MIGRATION_SMOKE_KEEP_STACK` | `runtime knob` | Defaults to off | Functional smoke cleanup | Parse as explicit truthy flag |
| `MIGRATION_SMOKE_GOLDEN_DIR` | `safe default` | Defaults to mounted fixtures | Functional smoke | Path must exist in context container |
| `MIGRATION_SMOKE_ORGANIZATION_ID` | `safe default` | Defaults to `functional-smoke-org` | Tenant-scoped functional smoke | Must identify the dedicated smoke organization and never select another tenant's state |
| `MIGRATION_SMOKE_PROBE_ATTEMPTS` | `runtime knob` | Safe default `60` | Functional smoke probes | Parse as positive integer |
| `MIGRATION_SMOKE_PROBE_DELAY_SECONDS` | `runtime knob` | Safe default `2` | Functional smoke probes | Parse as positive integer |
| `MIGRATION_SMOKE_LOG_TAIL_LINES` | `runtime knob` | Safe default `80` | Functional smoke diagnostics | Keep logs bounded and redacted |
| `CONTEXT_BROWSER_FIXTURE_HOST_PATH` | `safe default` | Defaults to `migration/context-browser-smoke.json` | Context browser smoke | Local fixture manifest path; do not commit generated artifact |
| `CONTEXT_BROWSER_ENV_FILE` | `safe default` | Defaults to `infrastructure/.env`; inherited from critical-path CI | Context browser smoke | CI must use the versioned fake-only env file |
| `CONTEXT_BROWSER_COMPOSE_PROJECT` | `safe default` | Empty locally; inherited from critical-path CI | Context browser smoke | Reuse the active critical-path project |
| `CONTEXT_BROWSER_COMPOSE_OVERRIDE` | `safe default` | Empty locally; inherited from critical-path CI | Context browser smoke | Reuse the test-only critical-path overlay |
| `CONTEXT_LIVE_PROVIDER_SMOKE_OUTPUT` | `safe default` | Defaults to `migration/context-live-provider-smoke.json` | Context live-provider smoke | Local redacted evidence path; do not commit generated artifact |
| `RUN_REAL_PROVIDER_TESTS` | `runtime knob` | Defaults to off | Live provider tests | Must be explicit; deterministic tests must not require it |
| `COMPOSE_FILE` | `safe default` | Defaults to infrastructure Compose file | Docker preflight | Path must exist |
| `ENV_FILE` | `safe default` | Defaults to `infrastructure/.env` | Docker preflight | Path must exist for stack targets |
| `SERVICE_TEST_ENV_FILE` | `safe default` | Defaults to versioned fake-only `.env.smoke.example` | Isolated service-test runner | Explicit override must exist and must not contain production credentials |
| `SERVICE_TEST_METRICS_DIR` | `safe default` | Defaults to `migration/service-tests` | Isolated service-test runner | Generated metrics remain local or short-lived CI artifacts |
| `SERVICE_TEST_HEALTH_TIMEOUT_SECONDS` | `runtime knob` | Safe default `180` | Isolated service-test runner | Parse as a positive integer and keep bounded |
| `CRITICAL_PATH_ENV_FILE` | `safe default` | Local critical path defaults to `infrastructure/.env`; CI uses `.env.smoke.example` | Critical-path validation | Explicit override must exist; CI must never consume the developer env file |
| `CRITICAL_PATH_COMPOSE_PROJECT` | `safe default` | Empty locally; CI uses `secpolicy-critical-path-ci` | Critical-path validation | CI project name must be dedicated to the job |
| `CRITICAL_PATH_COMPOSE_OVERRIDE` | `safe default` | Empty locally; CI uses `docker-compose.critical-path.yml` | Critical-path validation | Overlay contains test-only credentials and must flow into the smoke phase |
| `CRITICAL_PATH_REMOVE_VOLUMES` | `runtime knob` | Defaults to off locally; CI sets `1` | Critical-path cleanup | Remove volumes only for the dedicated CI project |
| `CRITICAL_PATH_METRICS_DIR` | `safe default` | Defaults to `migration/critical-path` | Critical-path CI wrapper | Generated metrics are short-lived CI artifacts |
| `MIGRATION_SMOKE_COMPOSE_PROJECT` | `safe default` | Empty locally; inherited from critical-path CI | Functional smoke | Use a dedicated project in automation |
| `MIGRATION_SMOKE_COMPOSE_OVERRIDE` | `safe default` | Empty locally; inherited from critical-path CI | Functional smoke | Explicit override must exist and remain test-only |
| `GRAFANA_ADMIN_USER` | `runtime knob` | Local default `admin` | Local Grafana service | Local/dev only |
| `GRAFANA_ADMIN_PASSWORD` | `runtime knob` | Local default `admin` | Local Grafana service | Local/dev only; do not reuse in production |
| `CHROMA_CONTAINER` | `safe default` | Defaults to local Compose Chroma container | Chroma backup tooling | Local/dev only |
| `CHROMA_IMAGE` | `safe default` | Defaults to local Chroma image | Chroma backup tooling | Local/dev only |
| `CHROMA_BACKUP_FILE` | `safe default` | Defaults to local workspace backup path | Chroma backup tooling | Path should stay under local workspace |
| `MIGRATION_SMOKE_ENV_FILE` | `safe default` | Defaults to ignored `infrastructure/.env.smoke`; when absent, mock smoke uses an ephemeral copy of `.env.smoke.example` | Functional smoke | Explicit overrides must exist; must contain fake-only deterministic values |
| `MIGRATION_SMOKE_REQUIRE_REAL_CONFIG` | `runtime knob` | Defaults to off | Functional smoke | Parse as explicit truthy flag |
| `MIGRATION_SMOKE_REQUIRE_RAG_READY` | `runtime knob` | Defaults to off | Functional smoke | Parse as explicit truthy flag |
| `MIGRATION_SMOKE_RAG_MODE` | `runtime knob` | Defaults to mock-compatible mode | Functional smoke RAG preparation | Restrict to documented smoke modes |
| `MIGRATION_SMOKE_RAG_READY_TIMEOUT_SECONDS` | `runtime knob` | Safe bounded timeout | Functional smoke RAG readiness wait | Parse as positive integer |
| `MIGRATION_SMOKE_RAG_READY_POLL_SECONDS` | `runtime knob` | Safe bounded poll interval | Functional smoke RAG readiness wait | Parse as positive integer |
| `MIGRATION_SMOKE_PIPELINE_JOB_TIMEOUT_SECONDS` | `runtime knob` | Safe bounded timeout | Functional smoke async pipeline polling | Parse as positive integer |
| `MIGRATION_SMOKE_PIPELINE_JOB_POLL_SECONDS` | `runtime knob` | Safe bounded poll interval | Functional smoke async pipeline polling | Parse as positive integer |
| `MIGRATION_SMOKE_CHROMA_BACKUP_FILE` | `safe default` | Defaults to local workspace backup path | Functional smoke backup mode | Path should stay under local workspace |
| `MIGRATION_SMOKE_CHROMA_BACKUP_AFTER_REFRESH` | `runtime knob` | Defaults to off | Functional smoke refresh mode | Parse as explicit truthy flag |

## Example Values

Use fake local placeholders in examples:

```env
FLASK_SECRET_KEY=fake-local-flask-secret
OPENAI_API_KEY=fake-local-openai-key
MISTRAL_API_KEY=fake-local-mistral-key
```

Do not use examples that resemble live provider key prefixes or personal
tokens. They invite accidental use and make reviews harder.

## Runtime Separation

The bundled Dockerfiles and `infrastructure/docker-compose.yml` are local
development contracts. They publish host ports, bind-mount service directories,
run the Flask development server, and may use fake local secrets. They are valid
for deterministic local smoke and developer diagnostics, not as production
deployment artifacts.

Local-only settings include `FLASK_ENV=development`, `FLASK_RUN_DEBUG=1`,
`SESSION_COOKIE_SECURE=false`, fake provider keys, mock agent configs, host port
mappings, and bind mounts. The default local contract keeps
`FLASK_RUN_DEBUG=0` and `DEBUG=false`; enabling either is an explicit developer
override.

Developer stack commands use the ignored `infrastructure/.env`, bootstrapped
from `.env.example` when appropriate. Functional smoke runs may use
deterministic workload fixtures with `TESTING=true`; normal
`make up` with `TESTING=false` rejects those keys. Run
`.venv/bin/python scripts/provision_local_workload_keys.py --tenant-id <local-organization-id>`
before normal startup to replace them with fresh Ed25519 keys in the ignored
env file. The candidate private key is written separately to ignored
`infrastructure/.env.candidate.local`; never distribute a caller private key
to a receiver. The command rotates keys on every run, so coordinate restarts.
Default functional smoke runs are
isolated from that personal file: they use ignored `.env.smoke`, or an
ephemeral copy of the versioned fake-only `.env.smoke.example` when the local
smoke file is absent. Only an explicit
`MIGRATION_SMOKE_REQUIRE_REAL_CONFIG=1` run may consume `.env`.

Production environments must inject real secrets through a secret manager or
equivalent runtime environment, keep `DEBUG=false`, use secure cookies behind
TLS/reverse proxy termination, avoid bind-mounted mutable source directories,
and use managed or operationally backed MongoDB/Chroma storage. INIT-04 owns CI
workflow implementation, and INIT-11 owns service-to-service authentication.

## Validation Policy

Minimum evidence by change type:

- Contract/docs only: static contract coverage test, code-search cross-check,
  and no real secret-like values.
- `.env.example` or Compose changes:
  `docker-compose -f infrastructure/docker-compose.yml --env-file infrastructure/.env config --quiet`.
- App config validation changes: focused `test_app_init.py` tests for affected
  services.
- Docker/runtime changes: `make up`, `/ready` checks, and affected service
  tests.
- RAG/Chroma config changes: `make policy-tests` and
  `make policy-rag-validate`.
- Cross-service config changes: `make critical-path-validation`.
- Redaction changes: sentinel-secret tests and smoke artifact review.
  Diagnostic scripts that print readiness responses or container logs must pass
  output through `scripts/redaction.sh`.

If a validation command cannot run because of dependency, network, or local
environment constraints, record it as blocked. Do not describe blocked evidence
as validated.

## Contract Compliance Tests

The first line of defense is static coverage: variables consumed by app
factories, provider clients, Dockerfiles, Compose, and operational scripts must
appear in this contract. This prevents new config from being added silently.

Behavioral coverage belongs with the PR that changes behavior:

- Required secret variables: app-init tests for missing values outside
  `TESTING=true`.
- URL and timeout variables: malformed-value tests before service calls.
- RAG/Chroma variables: policy-agent service tests plus
  `make policy-rag-validate`.
- Provider variables: focused client tests and opt-in real-provider tests only.
- Redaction variables: sentinel-secret tests against responses, logs, and smoke
  artifacts.

Static coverage proves the contract mentions a variable. Behavioral tests prove
the service handles that variable correctly.

## Handoff Notes

- INIT-04 should consume this contract when deciding GitHub Actions variables,
  repository secrets, and informational versus required gates.
- INIT-11 keeps `POLICY_CALLBACK_TOKEN` for the separate Policy-to-Context
  callback. Policy and Validator mutations require Ed25519-signed workload
  tokens; the former `SERVICE_AUTH_TOKEN` is not accepted. Context alone holds
  `WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64` and
  `WORKLOAD_CONTEXT_SIGNING_KID`; Validator alone holds
  `WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64` and
  `WORKLOAD_VALIDATOR_SIGNING_KID`. Policy/Validator receive only the relevant
  `WORKLOAD_*_VERIFY_KEYS` public registries. Candidate callers must hold
  their own private key and `kid`; receivers get only
  `WORKLOAD_CANDIDATE_VERIFY_KEYS`.
  Each caller sends a fresh `Authorization: Bearer` token with its fixed service
  identity, target audience, one allowed route scope, verified tenant, exact
  POST path, issued/expiry times (60 seconds), and random nonce. The target
  checks the signature and claims, then atomically records the nonce in Mongo
  with TTL to reject replay across workers. Mongo unavailable fails closed.
  `X-Tenant-ID` is metadata only and must match the signed tenant when sent.
  Context signs the organization resolved from the human session or tenant-
  validated pipeline job; Validator signs only the tenant from its verified
  Context request. Each verifier registry binds a `kid` and public key to an
  explicit tenant allowlist; candidate keys bind to one tenant. Provision
  distinct random signing seeds per deployment outside source control. Rotate
  by publishing the new public key first, then switching the caller's signing
  `kid`; retain at most one previous public key with `accept_until` bounded to
  600 seconds, and remove it after the overlap. Never log bearer values. The
  deterministic seeds and broad tenant IDs in `.env*.example` are test-only,
  not a deployment authorization policy. This does not make Policy or
  Validator persistence tenant-bound; that remains INIT-26 work.
- INIT-13 and INIT-15 remain responsible for retrieval behavior, indexing
  quality, and benchmark promotion. INIT-02 only governs the config surface.
