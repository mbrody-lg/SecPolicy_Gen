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
| `TESTING` | `safe default` | Defaults to `false` | App factory/tests | Parse as explicit truthy flag |
| `DEBUG` | `runtime knob` | Defaults to `false` | App factory/log behavior | Example defaults to `false`; dev override only |
| `MONGO_URI` | `required` | Local Docker default may be documented | Flask-PyMongo | Missing/malformed handling should be deterministic |
| `POLICY_AGENT_URL` | `required` | Docker default `http://policy-agent:5000` | Context to policy handoff | Validate as service URL before use |
| `VALIDATOR_AGENT_URL` | `required` | Docker default `http://validator-agent:5000` | Context to validator handoff | Validate as service URL before use |
| `CONFIG_PATH` | `required` | Defaults to `app/config/context_agent.yaml` on host; Compose passes container path | Agent config loading | Path should be explicit in Docker |
| `QUESTIONS_CONFIG_PATH` | `required` | Defaults to `app/config/context_questions.yaml` on host; Compose passes container path | Question/prompt config loading | Path should be explicit in Docker |
| `OPENAI_API_KEY` | `secret` | No real example value | OpenAI client | Required only for non-mock provider execution |
| `OPENAI_API_URL` | `runtime knob` | Safe provider default may be documented | OpenAI client | Compose should pass explicitly when used |
| `POLICY_AGENT_TIMEOUT_SECONDS` | `runtime knob` | Safe default `30` | Policy handoff HTTP calls | Parse as positive numeric value |
| `VALIDATOR_AGENT_TIMEOUT_SECONDS` | `runtime knob` | Safe default `30` | Validator handoff HTTP calls | Parse as positive numeric value |
| `MAX_CONTENT_LENGTH` | `runtime knob` | Safe default `262144` | Flask request limits | Parse as positive integer |
| `SESSION_COOKIE_SECURE` | `runtime knob` | Local default `false`; non-local should be `true` | Flask session cookie | Parse as explicit truthy flag |
| `TRUSTED_HOSTS` | `runtime knob` | Optional local list | Flask host validation | Parse comma-separated host list |
| `CONTEXT_IMPORT_PATH` | `safe default` | Defaults to example answers path in container tooling | YAML fixture import | Host/tool-only unless imported in runtime |

## Policy Agent

| Variable | Class | Default policy | Used by | Validation expectation |
|----------|-------|----------------|---------|------------------------|
| `FLASK_SECRET_KEY` | `secret`, `required` | Required outside `TESTING`; fake local only in examples | Flask session signing | App init fails safely when missing outside tests |
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
| `RAG_VALIDATE_CHROMA` | `runtime knob` | Defaults to off | RAG validate-only script | Parse as explicit boolean flag |
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
| `MIGRATION_SMOKE_PROBE_ATTEMPTS` | `runtime knob` | Safe default `60` | Functional smoke probes | Parse as positive integer |
| `MIGRATION_SMOKE_PROBE_DELAY_SECONDS` | `runtime knob` | Safe default `2` | Functional smoke probes | Parse as positive integer |
| `MIGRATION_SMOKE_LOG_TAIL_LINES` | `runtime knob` | Safe default `80` | Functional smoke diagnostics | Keep logs bounded and redacted |
| `RUN_REAL_PROVIDER_TESTS` | `runtime knob` | Defaults to off | Live provider tests | Must be explicit; deterministic tests must not require it |
| `COMPOSE_FILE` | `safe default` | Defaults to infrastructure Compose file | Docker preflight | Path must exist |
| `ENV_FILE` | `safe default` | Defaults to `infrastructure/.env` | Docker preflight | Path must exist for stack targets |

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
- INIT-11 should define future service-auth secrets and trust model before any
  new service-to-service credential is introduced.
- INIT-13 and INIT-15 remain responsible for retrieval behavior, indexing
  quality, and benchmark promotion. INIT-02 only governs the config surface.
