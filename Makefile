# Infrastructure directory
INFRA_DIR=infrastructure

DOCKER_COMPOSE_CMD=$(shell scripts/docker_preflight.sh --print-compose 2>/dev/null || printf 'docker-compose')
COMPOSE=$(DOCKER_COMPOSE_CMD) -f $(INFRA_DIR)/docker-compose.yml --env-file $(INFRA_DIR)/.env
LINT_PYTHON=$(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

.PHONY: all docker-preflight up down clean rebuild logs shell-context context-tests context-import policy-shell policy-tests policy-vectorize policy-rag-validate validator-shell validator-tests functional-smoke critical-path-validation bootstrap-test-env host-fast-tests lint help

## Verify docker and compose prerequisites
docker-preflight:
	@bash scripts/docker_preflight.sh

## Start all infrastructure
up: docker-preflight
	$(COMPOSE) up --build -d

## Stop all infrastructure
down: docker-preflight
	$(COMPOSE) down

## Stop and remove containers, networks, and volumes
clean: docker-preflight
	$(COMPOSE) down -v --remove-orphans

## Rebuild containers
rebuild: docker-preflight
	$(COMPOSE) up --build -d --force-recreate

## Show logs for all services
logs: docker-preflight
	$(COMPOSE) logs -f

## Enter the container agent-context
shell-context: 
	docker exec -it context_agent_web bash

## Run tests for agent-context
context-tests: 
	docker exec context_agent_web pytest

## Run tests for agent-context
context-import: 
	docker exec -it context_agent_web python generate_context_from_yaml.py

## Enter the policy-agent container
policy-shell: 
	docker exec -it policy_agent_service bash

## Run tests for policy-agent
policy-tests: 
	docker exec policy_agent_service pytest

## Run tests for policy-agent
policy-vectorize: 
	docker exec policy_agent_service python scripts/index_pdfs_to_chroma.py

## Validate policy-agent RAG manifest and source paths without indexing
policy-rag-validate:
	docker exec policy_agent_service python scripts/index_pdfs_to_chroma.py --validate-only --validate-chroma

## Enter the validator-agent container
validator-shell: 
	docker exec -it validator_agent_service bash

## Execute testos for validator-agent
validator-tests:
	docker exec validator_agent_service pytest

## Run full functional smoke in docker (end-to-end) using example fixtures
functional-smoke:
	./scripts/run_docker_functional_smoke.sh

## Run the critical Context -> Policy -> Validator validation path with CI-aligned evidence
critical-path-validation:
	./scripts/run_critical_path_validation.sh

## Bootstrap a reproducible local test environment in .venv
bootstrap-test-env:
	bash scripts/bootstrap-test-env.sh

## Run fast/route host tests with service-isolated imports
host-fast-tests:
	bash scripts/run-fast-or-route-tests.sh

## Run pylint with root pyproject.toml configuration
lint:
	$(LINT_PYTHON) -m pylint --rcfile=pyproject.toml policy-agent context-agent validator-agent

## Help
help:
	@echo "Makefile for multi-agent project"
	@echo ""
	@echo "make docker-preflight -> Verify Docker and Compose prerequisites"
	@echo "make up 			-> Start all infrastructure"
	@echo "make down 		-> Stop and remove containers"
	@echo "make clean 		-> Stop + remove volumes"
	@echo "make rebuild 		-> Rebuild services"
	@echo "make logs 		-> Show live logs"
	@echo "make context-shell 	-> Access context-agent shell"
	@echo "make context-tests 	-> Run tests inside context-agent"
	@echo "make context-import 	-> Run sample content import"
	@echo "make policy-shell 	-> Access policy-agent shell"
	@echo "make policy-tests 	-> Run tests inside policy-agent"
	@echo "make policy-vectorize 	-> Run data vectorization inside policy-agent"
	@echo "make policy-rag-validate -> Validate RAG manifest/source paths without indexing"
	@echo "make validator-shell 	-> Access validator-agent shell"
	@echo "make validator-tests 	-> Run tests within validator-agent"
	@echo "make functional-smoke 	-> Run full docker functional smoke pipeline"
	@echo "make critical-path-validation -> Run context/policy/validator suites plus smoke"
	@echo "make bootstrap-test-env -> Install local test dependencies into .venv"
	@echo "make host-fast-tests 	-> Run fast/route host tests per service"
	@echo "make lint 		-> Run pylint using root pyproject.toml config"
