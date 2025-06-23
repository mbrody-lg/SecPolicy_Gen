# Policy-Agent

## Project Description
**Policy-Agent** is a Flask-based microservice designed to generate and update security policies based on a business context. It uses a Retrieval-Augmented Generation (RAG) approach to enrich prompts with relevant information obtained from a vector database (Chroma) and a language backend (OpenAI). The generated policies are stored in MongoDB, along with metadata (version, language, state, and timestamps).

### Main Goals
1. Receive a context + (context_id) and generate a single policy using a multi-role strategy defined in a YAML configuration file (`policy-agent.yaml`).
2. Allow updating of an existing policy, with mandatory field control and data validation.
3. Integrate with other agents (Context-Agent, Validator-Agent) in a microservices architecture, using HTTP calls within an internal network (Docker).

### Prerequisites

1. Docker & Docker Compose (preferred to simplify installation of MongoDB and Chroma).
2. Python 3.9+ (if running locally without Docker).
3. Environment variables review env.example):

        OPENAI_API_URL
        OPENAI_API_KEY
        MONGO_URI (ex.: mongodb://localhost:27017/policy-agent-db)
        CHROMA_HOST (chroma hostname)
        CHROMA_PORT (when using Chroma via HTTP)
        CHROMA_COLLECTIONS_PATH on multicolection configuration
        FLASK_SECRET_KEY
        FLASK_ENV
        CONFIG_PATH (path to file policy-agent.yaml, inside Docker container by default on /config/policy-agent.yaml)

### Configuració

#### Fitxer YAML (policy-agent.yaml)

- roles: Llista seqüencial de rols que l’agent executarà. Cada rol ha de contenir com a mínim:

        name: Nom descriptiu del rol (ex. “RAG”, “PostProcessing”).
        type: vector (per a RAG) o openai (prompts simples).
        instructions: Plantilla de text que l’agent farà servir per a cada rol. Pot incloure placeholders com {context_fragments}, {original_prompt}.
        model: Nom del model OpenAI (ex. gpt-4o, gpt-4o-mini).
        temperature: Valor float entre 0.0 i 1.0. a més valor més "improvització" de l'agent
        max_tokens: Enter que limita la longitud de resposta.

- Si el Rol (p.ex. rol RAG) ha d'utilitzar RAG cal que defineixi quines BBDD vectorals utilitzarà

            vector:
                Chroma:
                    collection: Nom/s de la col·lecció dins Chroma. [normativa, guia, sector...]
                    volume_name: Nom del volum (schema) per a Chroma.
                    model: Model d’embeddings (ex. intfloat/e5-base, bge-base-en).
                    chunk_size: Mida (caràcters) dels chunks que es generaran.
                    chunk_overlap: Solapament (caràcters) entre chunks. 10%/20% de chunk-size (al gust)

### Configuration

#### YAML file (policy-agent.yaml)

- roles: Sequential list of roles that the agent will execute. Each role must contain at least:

        name: Descriptive name of the role (e.g. “RAG”, “PostProcessing”).
        type: vector (for RAG) or openai (simple prompts).
        instructions: Text template that the agent will use for each role. Can include placeholders like {context_fragments}, {original_prompt}.
        model: Name of the OpenAI model (e.g. gpt-4o, gpt-4o-mini).
        temperature: Float value between 0.0 and 1.0. plus value plus "improvisation" of the agent
        max_tokens: Integer that limits the length of the response.

- If the Role (e.g. RAG role) must use RAG it must define which vectorial DBDDs it will use 

            vector: 
                Chrome: 
                    collection: Name/s of the collection/s in Chroma. Multiple config: [regulation, guide, sector...] 
                    volume_name: Name of the volume (schema) for Chroma. 
                    model: Model of embeddings (eg intfloat/e5-base, bge-base-en). 
                    chunk_size: 
                    chunk_overlap: Ususally 10%/20% chunk-size

### RAG Role
If you don't have RAG training files:

1. Download the example files all agencies provide lots of documentation as a base for your Agent
2. Place them in an accessible folder and update .env CHROMA_COLLECTIONS_PATH=/absolute/folder_path
2. Run the script:

        make policy-vectorize

3. Wait while the data is vectorized.
4. Update the RAG role configuration to your liking.

### Generate a new policy

    POST /generate_policy/<context_id>

- Path parameter: context_id
- Request body: Optional. If the agent follows a multi-role flow, the body can include additional parameters such as language or extra metadata that can be used later.
- Response:

        {
            "context_id": "<context_id>",
            "policy_id": "<ObjectId_assigned>",
            "language": "es",
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
                "role": "MPG",
                "model": "gpt-4o",
                "duration_ms": 800
                }
            ]
        }

### Update an existing policy (usually request sent by validator-agent returning status rejected/review )

    POST /generate_policy/<context_id>/update

- Path parameter: context_id (ObjectId as string).
- Request body (JSON) (all are required):

        {
            "context_id": "<context_id>",
            "language": "en",
            "policy_text": "Updated policy text...",
            "policy_agent_version": "v1.0.1",
            "generated_at": "2025-06-02T19:00:00Z",
            "status": "rejected | review",
            "reasons": ["New GDPR requirement detected."],
            "recommendations": ["Add reference to consent record."]
        }

- Response:
- 200 OK if updated successfully.
- 400 Bad Request if required fields are missing.
- 404 Not Found if no context exists with that context_id.

### Contribution

1. Create a “fork” of the project.
2. Clone your fork locally.
3. Create a branch dedicated to your feature (e.g. feat/add-some-role).
4. Make your changes and run all tests locally.
5. Open a “Pull Request” detailing the feature or fix you propose.

### License
This project is released under the MIT license. See the LICENSE file for more details.
