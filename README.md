# Multi-agent Project for Generation and Validation of Security Policies

## Description

This project is a modular microservices system that uses Artificial Intelligence to:
1. **Generate context** from user questions.
2. **Create security policies** based on standards (ISO 27001, GDPR, etc.) and regulatory data.
3. **Validate and review** the policies generated through consensus between specialized agents.

It is composed of three main agents:
- **Context‐Agent**: Manages the interaction with the user to capture contextual information through forms and wizards.
- **Policy‐Agent**: Applies Retrieval‐Augmented Generation (RAG) patterns to develop a security policy proposal based on the context and regulatory data sets.
- **Validator‐Agent**: Runs multiple rounds of validation (consensus) between sub‐agents responsible for different aspects (compliance, logic, tone, etc.) and, if necessary, requests revisions up to 3 rounds.

Each agent is a Flask service that:

- Reads a YAML configuration of roles (patterns from Liu et al. 2024: PassiveGoalCreator, ProactiveGoalCreator, PromptResponseOptimiser, RAG, etc.).
- Interacts with a database (MongoDB) to persist states, contexts, and results.
- Uses an HTTP client to access a Chroma service (vector database) in RAG mode.
- Can use OpenAI (via SDK in beta) or MockAgent for local testing.

---

## Links to the READMEs of the Subprojects

- [infrastructure/README.md](infrastructure/README.md)  
- [context-agent/README.md](context-agent/README.md)  
- [policy-agent/README.md](policy-agent/README.md)  
- [validator-agent/README.md](validator-agent/README.md)  

---
