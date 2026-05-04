# Infrastructure Setup

Complete Docker-based infrastructure for running the multi-agent security policy generation system.

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- Git (to clone the repository)
- A terminal/command line

### 2. Configure Environment

Create a `.env` file in the `infrastructure/` directory:

```env
# Required for all agents
OPENAI_API_KEY=sk-your-api-key-here
FLASK_SECRET_KEY=your-secret-key-here
FLASK_ENV=development

# Database
MONGO_URI=mongodb://mongo:27017/policy-gen-db

# Vector Database (RAG)
CHROMA_HOST=chroma
CHROMA_PORT=8000

# Service URLs (internal Docker network)
POLICY_AGENT_URL=http://policy-agent:5000
```

### 3. Start All Services

From the project root directory:

```bash
make up
```

This starts:
- **MongoDB** - Data persistence for all agents
- **Chroma** - Vector database for regulatory documents
- **Context Agent** - Web/API service at http://localhost:5003
- **Policy Agent** - API at http://localhost:5002
- **Validator Agent** - API at http://localhost:5001

### 4. Stop Services

```bash
make down
```

To remove all data as well:

```bash
make clean
```

## Services

### MongoDB
- **Port**: 27017
- **Databases**: 
  - `context-agent-db` - User contexts and Q&A history
  - `policy-agent-db` - Generated policies and versions
  - `validator-agent-db` - Validation rounds and decisions

### Chroma Vector Database
- **Port**: 8000
- **Purpose**: Stores embedded regulatory documents for RAG
- **Collections**: normativa, guia, sector, methodology
- **Access**: Internal Docker network only

### Agent Services
All agents run on separate ports and use internal Docker DNS:
- Context Agent: `context-agent:5000`
- Policy Agent: `policy-agent:5000`
- Validator Agent: `validator-agent:5000`

## Useful Commands

| Command | Purpose |
|---------|---------|
| `make up` | Start all services |
| `make down` | Stop all services |
| `make clean` | Stop and remove all data |
| `make rebuild` | Force rebuild all containers |
| `make logs` | View live logs from all services |
| `make host-fast-tests` | Run fast host-side checks across services |
| `make shell-context` | Access Context Agent shell |
| `make context-tests` | Run Context Agent tests |
| `make policy-shell` | Access Policy Agent shell |
| `make policy-tests` | Run Policy Agent tests |
| `make policy-vectorize` | Index PDFs to Chroma for RAG |
| `make validator-shell` | Access Validator Agent shell |
| `make validator-tests` | Run Validator Agent tests |
| `make functional-smoke` | Run the end-to-end Docker smoke pipeline |
| `make critical-path-validation` | Run the CI-aligned critical path ladder |

## Recommended Docker Validation Sequence

When a change affects container parity, service configuration, or cross-service orchestration, use this sequence from the repository root:

```bash
make up
make policy-tests
make validator-tests
make functional-smoke
```

Notes:
- The service test targets use non-interactive `docker exec`, so they work in automated terminal sessions and do not require `-it`.
- `make functional-smoke` now resolves each service's effective `CONFIG_PATH` before swapping mock configs, so the smoke run exercises the same config entrypoints used by the containers themselves.
- `make functional-smoke` also checks `/health` and `/ready` on `context-agent`, `policy-agent`, and `validator-agent`, and records minimal loop observability evidence through `X-Correlation-ID` plus a `/diagnostics/<correlation_id>` lookup.
- For host-only logic changes, run `make host-fast-tests` before or instead of the Docker sequence when container parity is not needed.
- For one-command evidence of the critical Context -> Policy -> Validator path, use `make critical-path-validation`; it runs `context-tests`, `policy-tests`, `validator-tests`, and then the smoke sequence.

## Docker Compose Structure

```
docker-compose.yml services:
├── mongo              # MongoDB database
├── chroma             # Vector database for RAG
├── context-agent      # Context gathering service
├── policy-agent       # Policy generation service
└── validator-agent    # Policy validation service
```

## Compose Readiness Map

The Compose stack uses container healthchecks as readiness gates, not just
startup ordering:

| Service | Readiness probe | Dependent services |
|---------|-----------------|--------------------|
| `mongo` | `db.adminCommand('ping')` through the Mongo shell inside the container | `context-agent`, `policy-agent`, `validator-agent` |
| `chroma` | Container start only; live usability is checked by `policy-agent /ready` through its Chroma client | `policy-agent` |
| `context-agent` | HTTP `GET /ready` on the container-local Flask port | External smoke and diagnostics checks |
| `policy-agent` | HTTP `GET /ready` on the container-local Flask port | External smoke and diagnostics checks |
| `validator-agent` | HTTP `GET /ready` on the container-local Flask port | External smoke and diagnostics checks |

Readiness invariants:
- Agents that require MongoDB do not start until `mongo` is `service_healthy`.
- `policy-agent` does not start until `mongo` is `service_healthy` and `chroma` has started; `policy-agent /ready` performs the live Chroma check in Docker through `CHROMA_READINESS_MODE=live`.
- Agent healthchecks remain bound to `/ready`; Docker readiness should reflect whether each service can accept application traffic, while dependency readiness reflects whether required backing services are accepting connections.
- Compose healthchecks are local container probes. Host port mappings are for developer access and are not used to prove inter-service readiness.
- `depends_on.condition: service_healthy` only gates container startup. It does not replace runtime retry/error handling if a dependency becomes unhealthy after an agent has started.

## Setting Up RAG Data

The Policy Agent uses a vector database to retrieve relevant regulations and guidelines.

### Add Regulatory Documents

1. **Prepare PDF files** in a folder:
   - ISO 27001 documentation
   - GDPR guides
   - CIS Controls
   - Industry-specific regulations

2. **Configure RAG sources** in the policy-agent manifest, or point
   `RAG_SOURCES_PATH` at an alternate manifest:
   ```env
   RAG_SOURCES_PATH=/policy-agent/app/config/rag_sources.yaml
   ```

3. **Validate manifest and source paths**:
   ```bash
   make policy-rag-validate
   ```

4. **Index documents**:
   ```bash
   make policy-vectorize
   ```

5. **Wait for completion** - Processing time depends on document size

6. **Update policy-agent.yaml** to reference the collections

## Networking

All services communicate through Docker's internal network. External access points:

| Service | Port | Access |
|---------|------|--------|
| Context Agent Web/API | 5003 | http://localhost:5003 |
| Policy Agent API | 5002 | http://localhost:5002 |
| Validator Agent API | 5001 | http://localhost:5001 |
| MongoDB | 27017 | localhost:27017 (host only) |
| Chroma | 8000 | Internal Docker network |

## Troubleshooting

### Services Won't Start
- Check Docker is running: `docker ps`
- Review logs: `make logs`
- Ensure ports 27017, 8000, 5003, 5002, and 5001 are available

### MongoDB Connection Error
- Verify `MONGO_URI` in `.env`
- Check MongoDB container is running: `docker ps | grep mongo`
- View MongoDB logs: `make logs`

### Chroma Not Indexing
- Verify `RAG_SOURCES_PATH` points to the intended manifest
- Verify source paths inside `rag_sources.yaml` are mounted and readable
- Ensure PDF files are readable
- Check vectorization logs during processing

### Memory Issues
- Docker needs adequate RAM (at least 4GB recommended)
- Reduce number of concurrent operations
- Close other applications consuming memory

## Development Mode

To modify and test locally:

### 1. Access Agent Shell
```bash
make shell-context    # Enter Context Agent container
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Tests
```bash
pytest
```

### 4. Make Changes
Edit code in your local editor and reload in the container.

## Production Deployment

For production:

1. **Set environment variables securely** - Use a secrets management service
2. **Use production models** - Configure with gpt-4o instead of gpt-4o-mini
3. **Enable HTTPS** - Add reverse proxy (Nginx, Traefik)
4. **Set appropriate logging** - Configure log aggregation
5. **Back up MongoDB** - Set up regular backup strategy
6. **Monitor services** - Use the built-in `/health` and `/ready` endpoints plus the Docker Compose `healthcheck` probes now wired to `/ready` on each agent service

## Extensibility

### Adding New Backend Services (Claude, Mistral, etc.)

1. **Create service directory**:
   ```
   context-agent/app/agents/mistral/
   ```

2. **Implement agent**:
   - `client.py` - SDK integration
   - `agent.py` - Agent class inheriting from `base.Agent`
   - `roles/` - Role implementations

3. **Register in factory** - Auto-discovered from directory structure

4. **Add to docker-compose.yml**:
   ```yaml
   mistral-agent:
     build: ./mistral-agent
     environment:
       - MISTRAL_API_KEY=${MISTRAL_API_KEY}
   ```

5. **Update YAML configs** to use `type: mistral`

## License

MIT License - see [LICENCE.txt](../LICENCE.txt) for details
