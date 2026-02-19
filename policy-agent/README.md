# Policy Agent

An AI service that generates security policies based on business context and regulatory data. Uses retrieval-augmented generation (RAG) to incorporate relevant regulations and guidelines into policy documents.

## What It Does

The Policy Agent:
- Receives business context from the Context Agent
- Searches a database of regulatory documents for relevant information
- Generates comprehensive security policies using AI
- Stores policies with version tracking and metadata
- Accepts revision requests from the Validator Agent

## Key Features

- **RAG-Powered Generation**: Incorporates relevant regulations (ISO 27001, GDPR, CIS Controls, etc.)
- **Multi-Role Processing**: Applies different processing steps (RAG retrieval, policy generation, post-processing)
- **Version Control**: Tracks policy versions and updates
- **Integration Ready**: Works with Context Agent and Validator Agent in the system pipeline

## Prerequisites

- Docker (recommended)
- Python 3.11+ (for local development)
- MongoDB running and accessible
- Chroma vector database (for RAG feature)
- OpenAI API key

## Environment Variables

Create a `.env` file in the `policy-agent/` directory:

```env
OPENAI_API_KEY=sk-your-key-here
MONGO_URI=mongodb://mongodb:27017/policy-agent-db
CHROMA_HOST=chroma
CHROMA_PORT=8000
FLASK_SECRET_KEY=your-secret-key-here
FLASK_ENV=development
CONFIG_PATH=config/policy-agent.yaml
```

## Running the Service

### With Docker
```bash
make up
```

### Locally
```bash
pip install -r requirements.txt
python run.py
```

The service runs on `http://localhost:5000`

## Configuration

The agent behavior is defined in `config/policy-agent.yaml`:

### Roles Section
Each role represents a processing step in the policy generation pipeline:

```yaml
roles:
  - name: RAG                    # Retrieval-Augmented Generation
    type: vector
    model: gpt-4o
    temperature: 0.5
    max_tokens: 2000
    instructions: "Search regulatory data and extract relevant information..."
    vector:
      Chroma:
        collection: [normativa, guia, sector]
        volume_name: chroma
        model: intfloat/e5-base
        chunk_size: 1000
        chunk_overlap: 200

  - name: PolicyGeneration       # Generate the policy text
    type: openai
    model: gpt-4o
    temperature: 0.7
    max_tokens: 3000
    instructions: "Generate comprehensive security policy..."
```

**Role Parameters:**
- `name`: Descriptive identifier (e.g., "RAG", "PolicyGeneration")
- `type`: Processing type (`vector` for RAG, `openai` for AI processing)
- `model`: OpenAI model name (gpt-4o, gpt-4o-mini, etc.)
- `temperature`: Float 0.0-1.0 (lower = more deterministic, higher = more creative)
- `max_tokens`: Maximum response length
- `instructions`: Processing template with placeholders like `{context}`, `{regulations}`

### RAG Collections

To set up regulatory data for RAG:

1. **Prepare documents**: Gather PDF files (ISO 27001, GDPR guides, CIS Controls, etc.)
2. **Set path**: Update `.env` with `CHROMA_COLLECTIONS_PATH=/path/to/documents`
3. **Vectorize**: Run the indexing script
   ```bash
   make policy-vectorize
   ```
4. **Wait**: Processing takes time depending on file size
5. **Configure**: Update `policy-agent.yaml` with collection names (normativa, guia, sector, etc.)

See `config/examples/` for complete configuration examples.

## API Endpoints

### Generate a New Policy

```
POST /generate_policy/<context_id>
```

Generates a security policy based on business context.

**Parameters:**
- `context_id`: (path) The unique identifier from the Context Agent

**Request Body:** (optional)
```json
{
  "language": "en",
  "metadata": "additional information"
}
```

**Response:** (200 OK)
```json
{
  "context_id": "648a2f3b9e1c0d2e3f4g5h6i",
  "policy_id": "648a2f3b9e1c0d2e3f4g5h7j",
  "language": "en",
  "policy_text": "The full text of the generated policy...",
  "policy_agent_version": "v1.0.0",
  "generated_at": "2025-06-02T18:00:00Z",
  "status": "generated",
  "roles_executed": [
    {
      "role": "RAG",
      "model": "gpt-4o",
      "duration_ms": 1500
    },
    {
      "role": "PolicyGeneration",
      "model": "gpt-4o",
      "duration_ms": 800
    }
  ]
}
```

### Update an Existing Policy

```
POST /generate_policy/<context_id>/update
```

Updates a policy based on feedback from the Validator Agent. Called when policy needs revision.

**Parameters:**
- `context_id`: (path) The context identifier

**Request Body:** (all fields required)
```json
{
  "context_id": "648a2f3b9e1c0d2e3f4g5h6i",
  "language": "en",
  "policy_text": "Revised policy text with improvements...",
  "policy_agent_version": "v1.0.1",
  "generated_at": "2025-06-02T19:00:00Z",
  "status": "rejected",
  "reasons": ["GDPR compliance chapter missing"],
  "recommendations": ["Add GDPR consent record procedures"]
}
```

**Response:** (200 OK)
```json
{
  "message": "Policy updated successfully",
  "policy_id": "648a2f3b9e1c0d2e3f4g5h7j"
}
```

**Error Responses:**
- `400 Bad Request`: Missing required fields
- `404 Not Found`: Context ID doesn't exist

## Testing

Run the test suite:

```bash
make policy-tests
```

## Development

1. Create a feature branch: `git checkout -b feat/your-feature`
2. Make your changes
3. Add tests for new functionality
4. Run tests: `make policy-tests`
5. Submit a pull request

## Troubleshooting

**Chroma Connection Error**
- Ensure Chroma is running and accessible at `CHROMA_HOST:CHROMA_PORT`
- Check the Docker Compose configuration

**MongoDB Connection Error**
- Verify MongoDB is running
- Check `MONGO_URI` in `.env`

**OpenAI API Errors**
- Verify `OPENAI_API_KEY` is correct
- Check you have sufficient API credits
- Confirm model names exist in your API plan

**Vectorization Issues**
- Ensure PDFs are valid and readable
- Check file path is absolute
- Review logs during processing with `make logs`

**RAG Not Finding Relevant Data**
- Verify collections are properly indexed with `make policy-vectorize`
- Check collection names match in configuration
- Review chunk_size and chunk_overlap settings (usually 10-20% overlap)

## License

MIT License - see [LICENCE.txt](../LICENCE.txt) for details
