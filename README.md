# Security Policy Generation and Validation System

An AI-powered microservices platform that automatically generates and validates security policies based on regulatory standards and business context.

## Overview

The system consists of three specialized agents that work together in a pipeline:

1. **Context Agent** - Collects business information from users and generates context prompts
2. **Policy Agent** - Generates security policies using AI and regulatory data
3. **Validator Agent** - Reviews and refines policies through multiple validation rounds

## System Architecture

```
User Input → Context Agent → Policy Agent → Validator Agent → Approved Policy
                  ↓               ↓              ↓
              MongoDB         MongoDB        MongoDB
                              Chroma (RAG)
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)

### Running the Full System
```bash
make up
```

### Stopping the System
```bash
make down
```

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

For cross-service work, use this validation ladder and stop at the smallest level that proves the change unless the task affects runtime wiring:

1. `make up`
2. `make policy-tests`
3. `make validator-tests`
4. `make functional-smoke`

Use `make host-fast-tests` earlier in the loop when the change is host-test friendly and does not depend on Docker parity. Use the Docker-backed sequence above when the change affects container wiring, service-to-service calls, bootstrap/configuration behavior, or the full context -> policy -> validation pipeline.

When you need one reproducible command for the full critical loop, run `make critical-path-validation`. It executes `context-tests`, `policy-tests`, `validator-tests`, and the end-to-end smoke path in the same order we have been using as initiative evidence.

The current Docker test targets are intentionally non-interactive so they work in terminal automation and CI-like environments without requiring a TTY.

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
