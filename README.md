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

## Useful Commands

```bash
make up              # Start all services
make down            # Stop all services
make clean           # Stop and remove all data
make logs            # View live logs from all services
make context-tests   # Run Context Agent tests
make policy-tests    # Run Policy Agent tests
make validator-tests # Run Validator Agent tests
```

See [infrastructure/README.md](infrastructure/README.md) for complete command reference.

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
4. Submit a pull request

## License

MIT License - see [LICENCE.txt](LICENCE.txt) for details
