# Security Policy Generation and Validation System

An AI-powered microservices platform that automatically generates and validates security policies based on regulatory standards and business context.

## Overview

The system consists of three specialized agents that work together in a pipeline:

1. **Context Agent** - Collects business information from users and generates context prompts
2. **Policy Agent** - Generates security policies using AI and regulatory data
3. **Validator Agent** - Reviews and refines policies through multiple validation rounds

## System Architecture

```
Browser → OIDC Provider → Context Workplace
                              ├─ Intake and context building
                              ├─ Planning and asynchronous execution
                              └─ Final context
                                      ↓
                              Policy Agent ↔ Chroma RAG
                                      ↓
                              Validator Agent
                                      ↓
                              Validated policy
```

All agents persist their current local state in MongoDB and expose structured
logs and metrics through the observability stack.

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)

### Running the Full System
```bash
test -f infrastructure/.env || cp infrastructure/.env.example infrastructure/.env
make local-oidc-up
```

Then follow the [Local Application Validation](docs/playbooks/local-application-validation.md)
playbook for user provisioning, RAG bootstrap, the manual UI workflow, regression
levels, and failure diagnosis. Use `make up` instead when connecting to an
external OIDC provider already configured in `infrastructure/.env`.

### Stopping the System
```bash
make local-oidc-down
```

Use `make down` for the base stack without the local OIDC profile.

See [infrastructure/README.md](infrastructure/README.md) for detailed setup instructions.

## Agent Documentation

| Agent | Purpose | Documentation |
|-------|---------|---|
| Context Agent | Collect and structure user information | [context-agent/README.md](context-agent/README.md) |
| Policy Agent | Generate security policies with AI | [policy-agent/README.md](policy-agent/README.md) |
| Validator Agent | Validate and improve policies | [validator-agent/README.md](validator-agent/README.md) |
| Infrastructure | Docker setup and configuration | [infrastructure/README.md](infrastructure/README.md) |

## Service Playbooks

Tracked execution playbooks for service-specific testing, lint, and security workflows live in [docs/playbooks/README.md](docs/playbooks/README.md).

For the shared operational view of the critical loop, use the [Context -> Policy -> Validator runbook](docs/playbooks/context-policy-validator-loop.md). It covers `/health` and `/ready`, `X-Correlation-ID`, structured logs, diagnostics lookup, smoke evidence, and failure triage.

## Useful Commands

```bash
make up              # Start all services
make down            # Stop all services
make clean           # Stop and remove all data
make logs            # View live logs from all services
make host-fast-tests # Run fast host-side checks
make context-tests   # Run Context Agent tests
make policy-tests    # Run Policy Agent tests
make validator-tests # Run Validator Agent tests
make functional-smoke # Run end-to-end Docker smoke validation
make critical-path-validation # Run the CI-aligned critical path ladder
```

See [infrastructure/README.md](infrastructure/README.md) for complete command reference.

## Recommended Validation Flow

Use the validation levels and data-impact warnings in the
[Local Application Validation](docs/playbooks/local-application-validation.md)
playbook. `make functional-smoke` is deterministic and mock-backed;
`make functional-smoke-real-backup` and `make functional-smoke-real-full` are
the explicit real-provider and RAG paths.

## Project Structure

```
SecPolicy_Gen/
├── context-agent/      # User interaction & context generation
├── policy-agent/       # Security policy generation
├── validator-agent/    # Policy validation & refinement
├── infrastructure/     # Docker & deployment configuration
├── data/              # Regulatory and methodology documentation
└── Makefile           # Common commands
```

## Contributing

1. Fork the repository
2. Create a feature branch (`feat/your-feature`)
3. Make your changes and add tests
4. Update the relevant documentation or service playbook when workflow or behavior changes
5. Submit a pull request

## License

MIT License - see [LICENCE.txt](LICENCE.txt) for details
