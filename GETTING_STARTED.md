# Getting Started

The canonical installation and testing procedure is
[Local Application Validation](docs/playbooks/local-application-validation.md).

It covers:

- environment setup from `infrastructure/.env.example`
- local or external OIDC
- application membership provisioning
- Docker readiness and observability
- RAG backup, restore, model bootstrap, and source indexing
- Context, Policy, and Validator workplace validation
- deterministic and real-provider regression levels
- destructive-command warnings and failure diagnosis

For Compose topology and ports, use
[Infrastructure Setup](infrastructure/README.md). For configuration ownership and
secret handling, use the
[Environment Configuration Contract](docs/playbooks/environment-configuration.md).
