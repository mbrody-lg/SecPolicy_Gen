# Infrastructure directory
INFRA_DIR=infrastructure

COMPOSE=docker-compose -f $(INFRA_DIR)/docker-compose.yml --env-file $(INFRA_DIR)/.env
LINT_PYTHON=$(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

.PHONY: all up down clean rebuild logs shell-context context-tests context-import policy-shell policy-tests policy-vectorize validator-shell validator-tests functional-smoke cagent-phase1 cagent-phase1-case cagent-phase1-compare legacy-phase1-case phase1-shadow-case phase1-shadow-batch bootstrap-test-env lint help

## Start all infrastructure
up:
	$(COMPOSE) up --build -d

## Stop all infrastructure
down:
	$(COMPOSE) down

## Stop and remove containers, networks, and volumes
clean:
	$(COMPOSE) down -v --remove-orphans

## Rebuild containers
rebuild:
	$(COMPOSE) up --build -d --force-recreate

## Show logs for all services
logs:
	$(COMPOSE) logs -f

## Enter the container agent-context
shell-context: 
	docker exec -it context_agent_web bash

## Run tests for agent-context
context-tests: 
	docker exec -it context_agent_web pytest

## Run tests for agent-context
context-import: 
	docker exec -it context_agent_web python generate_context_from_yaml.py

## Enter the policy-agent container
policy-shell: 
	docker exec -it policy_agent_service bash

## Run tests for policy-agent
policy-tests: 
	docker exec -it policy_agent_service pytest

## Run tests for policy-agent
policy-vectorize: 
	docker exec -it policy_agent_service python scripts/index_pdfs_to_chroma.py

## Enter the validator-agent container
validator-shell: 
	docker exec -it validator_agent_service bash

## Execute testos for validator-agent
validator-tests:
	docker exec -it validator_agent_service pytest

## Run full functional smoke in docker (end-to-end) using example fixtures
functional-smoke:
	./scripts/run_docker_functional_smoke.sh

## Run Docker Agent Phase 1 scaffold
cagent-phase1:
	./scripts/run_cagent_phase1.sh

## Run Docker Agent Phase 1 dry run for one golden case
cagent-phase1-case:
	./scripts/run_cagent_phase1_case.sh $(CASE)

## Compare a Phase 1 candidate output against the legacy contract
cagent-phase1-compare:
	./scripts/run_cagent_phase1_compare.sh $(CANDIDATE) $(LEGACY)

## Capture one comparable legacy output for a golden case
legacy-phase1-case:
	./scripts/run_legacy_phase1_case.sh $(CASE) $(OUTPUT)

## Run a full Phase 1 shadow case: legacy, candidate, compare
phase1-shadow-case:
	./scripts/run_phase1_shadow_case.sh $(CASE) $(OUTPUT_DIR)

## Run a Phase 1 shadow batch across the golden set and summarize it
phase1-shadow-batch:
	./scripts/run_phase1_shadow_batch.sh $(GOLDEN_DIR) $(OUTPUT_DIR)

## Bootstrap a reproducible local test environment in .venv
bootstrap-test-env:
	bash scripts/bootstrap-test-env.sh

## Run pylint with root pyproject.toml configuration
lint:
	$(LINT_PYTHON) -m pylint --rcfile=pyproject.toml policy-agent context-agent validator-agent

## Help
help:
	@echo "Makefile for multi-agent project"
	@echo ""
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
	@echo "make validator-shell 	-> Access validator-agent shell"
	@echo "make validator-tests 	-> Run tests within validator-agent"
	@echo "make functional-smoke 	-> Run full docker functional smoke pipeline"
	@echo "make cagent-phase1 	-> Run the Docker Agent Phase 1 scaffold"
	@echo "make cagent-phase1-case CASE=... -> Run a Phase 1 dry run for one golden case"
	@echo "make cagent-phase1-compare CANDIDATE=... LEGACY=... -> Compare Phase 1 output with legacy JSON"
	@echo "make legacy-phase1-case CASE=... OUTPUT=... -> Capture one legacy comparable JSON"
	@echo "make phase1-shadow-case CASE=... OUTPUT_DIR=... -> Run legacy, candidate and comparison for one case"
	@echo "make phase1-shadow-batch GOLDEN_DIR=... OUTPUT_DIR=... -> Run shadow mode for the golden set and summarize results"
	@echo "make bootstrap-test-env -> Install local test dependencies into .venv"
	@echo "make lint 		-> Run pylint using root pyproject.toml config"
