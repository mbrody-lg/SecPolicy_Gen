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
- **Context Agent** - Web interface at http://localhost:3000
- **Policy Agent** - API at http://localhost:5001
- **Validator Agent** - API at http://localhost:5002

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
| `make context-shell` | Access Context Agent shell |
| `make context-tests` | Run Context Agent tests |
| `make policy-shell` | Access Policy Agent shell |
| `make policy-tests` | Run Policy Agent tests |
| `make policy-vectorize` | Index PDFs to Chroma for RAG |
| `make validator-shell` | Access Validator Agent shell |
| `make validator-tests` | Run Validator Agent tests |

## Docker Compose Structure

```
docker-compose.yml services:
├── mongo              # MongoDB database
├── chroma             # Vector database for RAG
├── context-agent      # Context gathering service
├── policy-agent       # Policy generation service
└── validator-agent    # Policy validation service
```

## Setting Up RAG Data

The Policy Agent uses a vector database to retrieve relevant regulations and guidelines.

### Add Regulatory Documents

1. **Prepare PDF files** in a folder:
   - ISO 27001 documentation
   - GDPR guides
   - CIS Controls
   - Industry-specific regulations

2. **Configure Chroma path** in `.env`:
   ```env
   CHROMA_COLLECTIONS_PATH=/absolute/path/to/documents
   ```

3. **Index documents**:
   ```bash
   make policy-vectorize
   ```

4. **Wait for completion** - Processing time depends on document size

5. **Update policy-agent.yaml** to reference the collections

## Networking

All services communicate through Docker's internal network. External access points:

| Service | Port | Access |
|---------|------|--------|
| Context Agent Web | 3000 | http://localhost:3000 |
| Policy Agent API | 5001 | http://localhost:5001 |
| Validator Agent API | 5002 | http://localhost:5002 |
| MongoDB | 27017 | localhost:27017 (host only) |
| Chroma | 8000 | Internal Docker network |

## Troubleshooting

### Services Won't Start
- Check Docker is running: `docker ps`
- Review logs: `make logs`
- Ensure ports 27017, 8000, 3000, 5001, 5002 are available

### MongoDB Connection Error
- Verify `MONGO_URI` in `.env`
- Check MongoDB container is running: `docker ps | grep mongo`
- View MongoDB logs: `make logs`

### Chroma Not Indexing
- Verify file path in `CHROMA_COLLECTIONS_PATH` is absolute
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
make context-shell    # Enter Context Agent container
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
6. **Monitor services** - Add health checks and monitoring

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
