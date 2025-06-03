# Infraestructura del projecte multi-agent

Aquest directori conté la infraestructura comuna per executar i coordinar els diferents agents del sistema mitjançant Docker i Docker Compose.

## Estructura general

```
multi-agent/
├── infraestructure/
│   ├── docker-compose.yml
│   ├── .env
│   ├── mongo/
├── Makefile
├── context-agent/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── openai/
│   │   │   │   ├── client.py
│   │   │   │   ├── agent.py
│   │   │   │   └── roles/
│   │   │   │       ├── proactive.py
│   │   │   │       └── optimiser.py
│   │   │   ├── mock/
│   │   │   │   ├── client.py
│   │   │   │   ├── agent.py
│   │   │   │   └── roles/
│   │   │   │       ├── proactive.py
│   │   │   │       └── optimiser.py
│   │   ├── config/
│   │   │   └── context_agent.yaml
│   │   │   └── context_questions.yaml
│   │   ├── routes/
│   │   │   └── routes.py
│   │   ├── static/
│   │   ├── services/
│   │   │   ├── logic.py
│   │   └── templates/
│   │       ├── base.html
│   │       ├── create_context.html
│   │       ├── context_detail.html
│   │       ├── dashboard.html
│   │       └── continue_context.html
│   ├── frontend/
│   │   ├── input.css
│   │   ├── package.json
│   │   ├── postcss.config.js
│   │   ├── tailwind.config.js
│   ├── tests/
│   └── run.py
│   └── Dockerfile
│   └── requirements.txt

```

---

## Execució ràpida

### 1. Requisits previs

- Docker
- Docker Compose
- Node.js (opcional per desenvolupament fora del contenidor)

### 2. Configura `.env`

A `infrastructure/.env`, revisa els exemples, pots utilitzar-ne únicament un, o un per cada agent:

```env
FLASK_SECRET_KEY=canvia-aixo-en-entorn-productiu
OPENAI_API_KEY=sk-...
MONGO_URI=mongodb://mongo:27017/contextdb
```

### 3. Llançar la infraestructura

Des de la carpeta `/`:

```bash
make up
```

- Això arrencarà tots els serveis:


        [x] context-agent
        [x] policy-agent
        [x] validator-agent
        [x] Container infrastructure-chroma
        [x] Container context_mongo
        [x] Container context_agent_web
        [x] Container policy_agent_service
        [x] Container validator_agent_service


## Tests

Per executar els tests dins del contenidor `context-agent`:

```bash
make context-tests
```

---

## Comandes útils

| Comanda                | Descripció                                           |
|------------------------|------------------------------------------------------|
| `make up`              | Arrenca tota la infraestructura                      |  
| `make down`            | Para i elimina contenidors                           |
| `make clean`           | Para + elimina volums                                |
| `make rebuild`         | Reconstrueix els serveis                             |
| `make logs`            | Mostra els logs en viu                               |
| `make context-shell`   | Accedeix al shell de context-agent                   |
| `make context-tests`   | Executa tests dins de context-agent                  |
| `make context-import`  | Executa importacio de contingut d'exemple            |
| `make policy-shell`    | Accedeix al shell de policy-agent                    |
| `make policy-tests`    | Executa tests dins de policy-agent                   |
| `make policy-vectorize`| Executa vectorització de dades dins de policy-agent  |
| `make validator-shell` | Accedeix al shell de validator-agent                 |
| `make validator-tests` | Executa tests dins de validator-agent                |
|------------------------|------------------------------------------------------|

## Extensibilitat

El sistema està dissenyat per afegir fàcilment nous tipus d’agents basats en diferents SDKs, mantenint una estructura modular i reutilitzable.
Per afegir un nou backend com Claude, Mistral, ...:

1. Duplica la carpeta `openai/` dins `app/agents/` i anomena-la `claude/`, `mistral/`,...
2. Implementa el teu `client.py` amb la lògica pròpia del SDK corresponent.
3. Implementa `agent.py`, assegurant-te que:
    - La classe hereti de `Agent` (de `base.py`)
    - S’enregistri correctament via `__init_subclass__` per utilitzar el patro AGENT_REGISTRY
4. Reutilitza o adapta els rols dins `roles/` (alguns patrons utilitzats son `ProactiveGoalCreator`, `PromptResponseOptimiser`, etc.) segons necessitat
5. Crea el YAML de configuració amb el tipus corresponent (type: `claude`, `openai`, `mistralai`)
6. No cal modificar `factory.py`: els nous agents es carreguen automàticament si segueixen l’estructura `app/agents/<type>/agent.py`.
7. Cada agent ha de definir el seu `Dockerfile`, `run.py`, i estructura modular
8. Afegir el servei nou a `docker-compose.yml`

## Consells

- El frontend utilitza Tailwind i es compila amb `npm run build` a la carpeta `frontend/`
- El CSS generat es copia a `app/static/css/tailwind.css` automàticament en el `Dockerfile`

### Contribució

1. Crea un “fork” del projecte.
2. Clona el teu fork localment.
3. Crea una branca dedicada (p. ex. feat/new-role-evaluation).
4. Fes els teus canvis i executa tots els tests, si crees noves funcions si us plau posa-li un mínim test:
5. Obre un “Pull Request” explicant la funcionalitat o correcció proposada.

### Llicència

Aquest projecte està publicat sota la llicència MIT. Consulta el fitxer LICENSE per a més detalls.