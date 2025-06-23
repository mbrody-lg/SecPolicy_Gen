# Infrastructure directory
INFRA_DIR=infrastructure

COMPOSE=docker-compose -f $(INFRA_DIR)/docker-compose.yml --env-file $(INFRA_DIR)/.env

.PHONY: all up down clean rebuild logs context-shell context-tests context-import policy-shell policy-tests policy-vectorize validator-shell validator-tests help

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
