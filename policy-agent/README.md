# Policy-Agent

## Descripció del projecte
**Policy-Agent** és un microservei basat en Flask dissenyat per generar i actualitzar polítiques de seguretat a partir d’un context empresarial. Utilitza un enfoc Retrieval-Augmented Generation (RAG) per enriquir els prompts amb informació rellevant obtinguda d’una base de dades vectorial (Chroma) i un backend de llenguatge (OpenAI). Les polítiques generades es guarden a MongoDB, juntament amb metadades (versió, idioma, estat, i timestamps).

### Objectius principals
1. Rebre un context + (context_id) i generar una política única mitjançant una estrategia de multiples rols definit en un fitxer de configuració YAML (`policy-agent.yaml`).
2. Permetre l’actualització d’una política existent, amb control de camps obligatoris i validació de dades.
3. Integrar-se amb altres agents (Context-Agent, Validator-Agent) en una arquitectura de microserveis, mitjançant crides HTTP dins d’una xarxa interna (Docker).

### Requisits previs

1. Docker & Docker Compose (preferible per simplificar la instal·lació de MongoDB i Chroma).
2. Python 3.9+ (si es vol executar localment sense Docker).
3. Variables d’entorn revisar env.example):

        OPENAI_API_URL
        OPENAI_API_KEY
        OPENAI_API_URL (si cal usar entorn d’OpenAI custom)
        MONGO_URI (per exemple, mongodb://localhost:27017/policy-agent-db)
        CHROMA_HOST i CHROMA_PORT (en cas d’usar Chroma via HTTP) i CHROMA_COLLECTIONS_PATH
        FLASK_SECRET_KEY
        FLASK_ENV
        CONFIG_PATH (ruta al fitxer policy-agent.yaml, dins del contenidor Docker normalment és /config/policy-agent.yaml)

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


### Rol RAG
Si no disposes de fitxers d'entrenament RAG:

1. Descarregar els fitxers d'exemple: https://drive.google.com/file/d/1KE2N4_7nIuFgL0hKrPz8zyLCUp-NQdTo/view?usp=drive_link
2. Colocar-los a una carpeta accesible i actualitzar .env CHROMA_COLLECTIONS_PATH=/absolute/folder_path
2. llançar l'script:

        make policy-vectorize

3. Esperar mentres es vectoritzen les dades.
4. Actualitza la configuració del rol RAG al teu gust.

### Generar una nova política

    POST /generate_policy/<context_id>

- Path parameter: context_id
- Cos de la petició: Opcional. Si l’agent segueix un flux multi-rol, el cos pot incloure paràmetres addicionals com language o metadades extra que es poden fer servir més endavant.
- Resposta:

        {
            "context_id": "<context_id>",
            "policy_id": "<ObjectId_assigned>",
            "language": "es",
            "policy_text": "El text complet de la política generada...",
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


### Actualitzar una política existent ( habitualment petició enviada per validator-agent retornant status rejected/review )

    POST /generate_policy/<context_id>/update

- Path parameter: context_id (ObjectId com a string). 
- Cos de la petició (JSON) (tots són obligatoris):

        {
            "context_id": "<context_id>",
            "language": "es",
            "policy_text": "Text actualitzat de la política...",
            "policy_agent_version": "v1.0.1",
            "generated_at": "2025-06-02T19:00:00Z",
            "status": "rejected | review",
            "reasons": ["S’ha detectat nou requisit GDPR."],
            "recommendations": ["Afegir referència al registre de consentiments."]
        }

- Resposta:
    - 200 OK si s’ha actualitzat correctament.
    - 400 Bad Request si falten camps obligatoris.
    - 404 Not Found si no existeix cap context amb aquell context_id.

### Contribució

1. Crea un “fork” del projecte.
2. Clona el teu fork localment.
3. Crea una branca dedicada a la teva funcionalitat (p. ex. feat/add-some-role).
4. Fes els teus canvis i executa tots els tests localment.
5. Obre un “Pull Request” detallant la funcionalitat o correcció que proposes.

### Llicència
Aquest projecte està publicat sota la llicència MIT. Consulta el fitxer LICENSE per a més detalls.