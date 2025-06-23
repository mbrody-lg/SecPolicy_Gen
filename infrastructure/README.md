# Multi-agent project infrastructure

This directory contains the common infrastructure for running and coordinating the different agents in the system using Docker and Docker Compose.

## General structure

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

## Quick Run

### 1. Prerequisites

- Docker
- Docker Compose
- Node.js (optional for out-of-container development)

### 2. Configure `.env`

In `infrastructure/.env`, review the examples, you can use only one, or one for each agent:

```env
FLASK_SECRET_KEY=change-in-pro-env
OPENAI_API_KEY=sk-...
MONGO_URI=mongodb://mongo:27017/contextdb
```

### 3. Launch the infrastructure

From the `/` folder:

```bash
make up
```

- This will start all the services:

        [x] context-agent
        [x] policy-agent
        [x] validator-agent
        [x] Container infrastructure-chroma
        [x] Container context_mongo
        [x] Container context_agent_web
        [x] Container policy_agent_service
        [x] Container validator_agent_service


## Tests

To run the tests inside the `context-agent` container:

```bash
make context-tests
```

---

## Useful commands

| Command                | Description                                          |
|------------------------|------------------------------------------------------|
| `make up`              | Start all infrastructure                             |  
| `make down`            | Stop and remove containers                           |
| `make clean`           | Stop + remove volumes                                |
| `make rebuild`         | Rebuild services                                     |
| `make logs`            | Show live logs                                       |
| `make context-shell`   | Access context-agent shell                           |
| `make context-tests`   | Run tests within context-agent                       |
| `make context-import`  | Run sample content import                            |
| `make policy-shell`    | Access policy-agent shell                            |
| `make policy-tests`    | Run tests within policy-agent                        |
| `make policy-vectorize`| Run data vectorization within policy-agent           |
| `make validator-shell` | Access validator-agent shell                         |
| `make validator-tests` | Run tests inside validator-agent                     |
|------------------------|------------------------------------------------------|

## Extensibility

The system is designed to easily add new types of agents based on different SDKs, maintaining a modular and reusable structure.
To add a new backend like Claude, Mistral, ...:

1. Duplicate the `openai/` folder inside `app/agents/` and name it `claude/`, `mistral/`,...

2. Implement your `client.py` with the logic of the corresponding SDK.
3. Implement `agent.py`, ensuring that:
- The class inherits from `Agent` (from `base.py`)
- It is correctly registered via `__init_subclass__` to use the AGENT_REGISTRY pattern
4. Reuse or adapt the roles in `roles/` (some patterns used are `ProactiveGoalCreator`, `PromptResponseOptimiser`, etc.) as needed
5. Create the configuration YAML with the corresponding type (type: `claude`, `openai`, `mistralai`)
6. There is no need to modify `factory.py`: new agents are loaded automatically if they follow the structure `app/agents/<type>/agent.py`.
7. Each agent must define its `Dockerfile`, `run.py`, and modular structure
8. Add the new service to `docker-compose.yml`

## Tips

- The frontend uses Tailwind and is compiled with `npm run build` in the `frontend/` folder
- The generated CSS is copied to `app/static/css/tailwind.css` automatically in the `Dockerfile`

### Contribution

1. Create a “fork” of the project.
2. Clone your fork locally.
3. Create a dedicated branch (e.g. feat/new-role-evaluation).
4. Make your changes and run all tests, if you create new features please put a minimum test:
5. Open a “Pull Request” explaining the proposed functionality or fix.

### License

This project is released under the MIT license. See the LICENSE file for more details.
