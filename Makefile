# Directori de la infraestructura
INFRA_DIR=infrastructure

COMPOSE=docker-compose -f $(INFRA_DIR)/docker-compose.yml --env-file $(INFRA_DIR)/.env

.PHONY: all up down clean rebuild logs context-shell context-tests context-import policy-shell policy-tests policy-vectorize validator-shell validator-tests help

## Arrenca tota la infraestructura
up:
	$(COMPOSE) up --build -d

## Para tota la infraestructura
down:
	$(COMPOSE) down

## Para i elimina contenidors, xarxes i volums
clean:
	$(COMPOSE) down -v --remove-orphans

## Reconstrueix els contenidors
rebuild:
	$(COMPOSE) up --build -d --force-recreate

## Mostra els logs de tots els serveis
logs:
	$(COMPOSE) logs -f

## Entra dins el contenidor de context-agent
context-shell:
	docker exec -it context_agent_web bash

## Executa testos per a context-agent
context-tests:
	docker exec -it context_agent_web pytest

## Executa testos per a context-agent
context-import:
	docker exec -it context_agent_web python generate_context_from_yaml.py
	
## Entra dins el contenidor de policy-agent
policy-shell:
	docker exec -it policy_agent_service bash

## Executa testos per a policy-agent
policy-tests:
	docker exec -it policy_agent_service pytest

## Executa testos per a policy-agent
policy-vectorize:
	docker exec -it policy_agent_service python scripts/index_pdfs_to_chroma.py

## Entra dins el contenidor de validator-agent
validator-shell:
	docker exec -it validator_agent_service bash

## Executa testos per a validator-agent
validator-tests:
	docker exec -it validator_agent_service pytest

## Ajuda
help:
	@echo "Makefile per al projecte multi-agent"
	@echo ""
	@echo "make up              	-> Arrenca tota la infraestructura"
	@echo "make down            	-> Para i elimina contenidors"
	@echo "make clean           	-> Para + elimina volums"
	@echo "make rebuild         	-> Reconstrueix els serveis"
	@echo "make logs            	-> Mostra els logs en viu"
	@echo "make context-shell   	-> Accedeix al shell de context-agent"
	@echo "make context-tests   	-> Executa tests dins de context-agent"
	@echo "make context-import  	-> Executa importacio de contingut d'exemple"
	@echo "make policy-shell    	-> Accedeix al shell de policy-agent"
	@echo "make policy-tests   		-> Executa tests dins de policy-agent"
	@echo "make policy-vectorize   	-> Executa vectorització de dades dins de policy-agent"
	@echo "make validator-shell    	-> Accedeix al shell de validator-agent"
	@echo "make validator-tests    	-> Executa tests dins de validator-agent"
