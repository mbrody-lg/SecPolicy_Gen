# Validator-Agent

## Descripció del projecte
**Validator-Agent** és un microservei basat en Flask dissenyat per validar polítiques generades pel **Policy-Agent**. El seu objectiu és executar diversos rols (agents de treball) per comprovar que la política compleix els estàndards de compliment (com ISO 27001, GDPR, etc.) i millorar-la si cal. S’executen fins a tres rondes de consens entre rols (AWC, AWL, AWT i EVA). En cas de desacord o necessitat de revisió, el **Validator-Agent** envia una sol·licitud de retroalimentació al **Policy-Agent**, que actualitza la política i torna a iniciar el procés de validació.

### Objectius principals
1. Rebre una política generada pel **Policy-Agent** i validar-la en 3 rondes com a màxim.
2. Cada ronda consisteix en:
   - Rols de validació:  
     - **AWC** (Agent Worker Compliance): Avalua el compliment normatiu.  
     - **AWL** (Agent Worker Logic): Comprova la coherència interna de la política.  
     - **AWT** (Agent Worker Tone): Verifica to i llenguatge adequats.  
     - **EVA** (Evaluator): Revisa els resultats anteriors i decideix si cal modificar la política.
   - Si algun rol detecta discrepàncies, el **Coordinator** sol·licita un nou cicle de validació després que l’**Evaluator** emeti suggeriments.
3. Notificar al **Policy-Agent** mitjançant una crida HTTP de retorn amb motius i recomanacions si la política necessita revisió o és rebutjada definitivament.
4. Desa l’historial de validacions a MongoDB (resultats parcials per ronda, decisions de l’`EVA`, timestamps, etc.).

### Requisits previs

1. Docker & Docker Compose (recomanat).
2. Python 3.9+ (si es vol executar sense Docker).
3. Variables d’entorn (fora de Docker):

        OPENAI_API_KEY
        MONGO_URI (p. ex. mongodb://localhost:27017/validator-agent-db)
        FLASK_SECRET_KEY
        CONFIG_PATH (ruta a validator-agent.yaml)
        POLICY_AGENT_URL (URL base del Policy-Agent, p. ex. http://policy-agent:5000)

### Configuració

#### Fitxer YAML (validator-agent.yaml)
Revisa la carpeta config/exemples/ i utilitza el que et sembli millor, compte! amb CONFIG_PATH

- `roles`: Llista de rols en l’ordre que s’executaran. Cada rol ha de contenir:

            name: Nom descriptiu (AWC, AWL, AWT, EVA).
            type: openai (només es suporten rols basats en OpenAI, Mock, excepcionalment MistralAI només a validator).
            instructions: Plantilla textual per al prompt d’OpenAI. Pot incloure placeholders per a les respostes anteriors (per a EVA).
            model: Nom del model OpenAI (ex. gpt-4o-mini), OpenRouter compatible (ex. openai/gpt-4o) o MistraAI (ex. mistral-medium-latest).
            temperature: Valor float entre 0.0 i 1.0.
            max_tokens: Enter per limitar la resposta.

        max_rounds: Nombre màxim de rondes de validació (en general, 3).
        validation:
            rounds: Nombre màxim de rondes de validació (en general, 3).
            consensus_threshold: Nombre màxim de consens necessari per l'acceptació d'una política (en general, 2).

### Ús de l’API

#### Iniciar validació d’una política

    POST /validate_policy/<context_id>
    Content-Type: application/json

- Path parameter: context_id
- Cos de la petició: Opcional

        {
            "context_id": "<ObjectId_com_a_string>",
            "policy_text": "Text complet de la política generada pel Policy-Agent...",
            "structured_plan": "Pla estructurat obtingut pel Policy-Agent...",
            "generated_at": "2025-06-02T18:00:00Z",
            "language": "es",                  // Opcional
            "policy_agent_version": "v1.0.0"   // Opcional
        }

- Resposta (200 Ok) [accepted -> context-agent, review | rejected -> policy-agent]:

        {
            "context_id": "<context_id>",
            "language": "es",
            "policy_text": "...",
            "structured_plan": "...",
            "generated_at": "2025-06-02T18:00:00Z",
            "policy_agent_version": "v1.0.0",
            "status": "rejected",                // "accepted", "review" o "rejected"
            "reasons": ["Manca capítol GDPR."],
            "recommendations": ["Incloure compliment GDPR."],
            "evaluator_analysis": {             // Només si existeix informació addicional
                "explanation": "L’EVA ha detectat que falta referència directa a GDPR..."
            }
        }

### Obtenir totes les validacions per context

    GET /validation/<context_id>

- Path parameter: context_id (String amb ObjectId).
- Resposta (200 OK):

        [
            {
                "_id": "650b8a1e5f4c2a0001d2f3b4",
                "context_id": "642e4f50e9f1a3b2c7d8e9f0",
                "round": 1,
                "results": {
                "AWC": { "result": "accepted", "reasons": [], "recommendations": [] },
                "AWL": { "result": "review", "reasons": ["Incoherència X."], "recommendations": ["Revisar Y."] },
                "AWT": { "result": "accepted", "reasons": [], "recommendations": [] },
                "EVA": { "result": "review", "reasons": ["Falta GDPR."], "recommendations": ["Afegir GDPR."] }
                },
                "timestamp": "2025-06-02T18:02:15.123456"
            },
            {
                "_id": "650b8a1e5f4c2a0001d2f3b5",
                "context_id": "642e4f50e9f1a3b2c7d8e9f0",
                "round": 2,
                "results": {
                "AWC": { "result": "rejected", "reasons": ["Incoherència A."], "recommendations": ["Afegir CIS Controls."] },
                "AWL": { "result": "accepted", "reasons": [], "recommendations": [] },
                "AWT": { "result": "accepted", "reasons": [], "recommendations": [] },
                "EVA": { "result": "accepted", "reasons": [], "recommendations": [] }
                },
                "timestamp": "2025-06-02T18:04:20.654321"
            }
        ]

### Eliminar totes les validacions d’un context (només en mode TESTING)

    DELETE /validation/<context_id>

- Path parameter: context_id.
- Resposta (200 OK):

    {
        "message": "2 validation(s) deleted for context_id: 642e4f50e9f1a3b2c7d8e9f0"
    }

### Contribució

1. Crea un “fork” del projecte.
2. Clona el teu fork localment.
3. Crea una branca dedicada (p. ex. feat/new-role-evaluation).
4. Fes els teus canvis i executa tots els tests, si crees noves funcions si us plau posa-li un mínim test:
5. Obre un “Pull Request” explicant la funcionalitat o correcció proposada.

### Llicència

Aquest projecte està publicat sota la llicència MIT. Consulta el fitxer LICENSE per a més detalls.