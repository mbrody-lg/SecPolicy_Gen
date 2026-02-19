# Context Agent

A web service that gathers business information from users through an interactive questionnaire and generates context prompts for policy generation.

## What It Does

The Context Agent:
- Presents users with a structured set of questions about their business
- Collects and stores answers in MongoDB
- Generates a formatted context prompt from the collected information
- Allows users to resume previous conversations

## Key Features

- **Interactive Questionnaire**: Questions guide users through business context (country, sector, compliance needs, etc.)
- **Multiple Conversations**: Each user can maintain separate context threads
- **Persistent Storage**: All Q&A history is saved in MongoDB for resuming or referencing
- **Context Prompt Generation**: Automatically creates formatted prompts for the Policy Agent

## Prerequisites

- Docker (recommended)
- Python 3.11+ (for local development)
- MongoDB running and accessible
- OpenAI API key

## Environment Variables

Create a `.env` file in the `context-agent/` directory:

```env
OPENAI_API_KEY=sk-your-key-here
MONGO_URI=mongodb://mongodb:27017/context-agent-db
FLASK_SECRET_KEY=your-secret-key-here
FLASK_ENV=development
CONFIG_PATH=config/context-agent.yaml
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

## API Endpoints

### Create a New Context
```
POST /context
```

Starts a new questionnaire session.

**Response:**
```json
{
  "context_id": "unique-id",
  "status": "in_progress",
  "current_question": {
    "id": "country",
    "text": "What country is your organization located in?"
  }
}
```

### Continue a Context
```
POST /context/<context_id>/answer
Content-Type: application/json

{
  "answer": "Spain"
}
```

Submit an answer and get the next question.

### Get Context Details
```
GET /context/<context_id>
```

Retrieve the current state of a context and the generated prompt.

**Response:**
```json
{
  "context_id": "unique-id",
  "status": "completed",
  "answers": {
    "country": "Spain",
    "sector": "Banking"
  },
  "context_prompt": "Generated prompt text..."
}
```

### List All Contexts
```
GET /contexts
```

Returns all saved contexts with filters (status, date, etc.)

## Configuration

The agent behavior is defined in `config/context-agent.yaml`:

### Questions Section
Lists the questions to ask users in order:
```yaml
questions:
  - id: country
    question: "What country is your organization located in?"
  - id: sector
    question: "What sector does your organization operate in?"
```

### Roles Section
Defines how to process answers after collection:
```yaml
roles:
  - name: PassiveGoalCreator
    type: openai
    model: gpt-4o-mini
    temperature: 0.7
    max_tokens: 1000
    instructions: "Template text for processing..."
```

See `config/examples/` for complete configuration examples.

## Testing

Run the test suite:

```bash
make context-tests
```

## Development

1. Create a feature branch: `git checkout -b feat/your-feature`
2. Make your changes
3. Add tests for new functionality
4. Run tests: `make context-tests`
5. Submit a pull request

## Troubleshooting

**MongoDB Connection Error**
- Ensure MongoDB is running and accessible at the MONGO_URI
- Check the connection string in `.env`

**OpenAI API Errors**
- Verify your `OPENAI_API_KEY` is correct
- Check you have sufficient API credits

**Configuration Issues**
- Verify `CONFIG_PATH` points to a valid YAML file
- Check YAML syntax with a YAML validator

## License

MIT License - see [LICENCE.txt](../LICENCE.txt) for details
