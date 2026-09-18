# External Agent Configuration

The three runtime agent YAML files are treated as external control-plane
configuration, not project source code.

Operational configuration lives outside git by default:

- `runtime/agent-config/context_agent.yaml`
- `runtime/agent-config/context_questions.yaml`
- `runtime/agent-config/policy_agent.yaml`
- `runtime/agent-config/validator_agent.yaml`

The repository keeps only executable contracts, tests, bootstrap tooling, mock
configs, and baseline examples. Each project can enrich its local agent
configuration without committing private prompts, regulatory tuning, or
project-specific operating rules.

## Bootstrap

Create missing local files from the repository baselines:

```bash
make agent-config-bootstrap
```

Existing files are preserved.

## Validation

Validate the external files against the service runtimes:

```bash
make validate-agent-config
```

This builds the service images and validates each config with the code that will
load it at runtime.

## Runtime Paths

Docker Compose mounts the local config directory at `/agent-config` and uses:

- `CONTEXT_AGENT_CONFIG_PATH`, default `/agent-config/context_agent.yaml`
- `CONTEXT_QUESTIONS_CONFIG_PATH`, default `/agent-config/context_questions.yaml`
- `POLICY_AGENT_CONFIG_PATH`, default `/agent-config/policy_agent.yaml`
- `VALIDATOR_AGENT_CONFIG_PATH`, default `/agent-config/validator_agent.yaml`

Override `AGENT_CONFIG_DIR` to use another host directory. For production-like
hosts, use a system configuration path such as `/etc/secpolicy-gen/agents`.

## Smoke Tests

`make functional-smoke` runs in deterministic mock mode and intentionally uses
the internal mock-swappable service config paths. Real smoke runs use the
external `/agent-config` defaults unless the path variables above are overridden.
