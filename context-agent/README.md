# Context-Agent

## Descripció del projecte
**Context-Agent** és un microservei basat en Flask dissenyat per recollir informació estructurada (context empresarial) de l’usuari i generar un prompt de context per a posterior ús pels altres agents (Policy-Agent i Validator-Agent). Funciona com un “wizard” de preguntes que permet crear o continuar múltiples fils de context independents. Tota la informació de cada context es desa a MongoDB, incloent l’historial de preguntes i respostes, per tal de poder reprendre o referenciar contextos en qualsevol moment.

### Objectius principals
1. Oferir un flux interàctiu de preguntes per tal que l’usuari pugui descriure el seu context empresarial (país, regió, sector, actius, metodologies, necessitats, etc.).  
2. Generar un prompt de context amb la informació recollida, aplicant patrons com `PassiveGoalCreator`, `ProactiveGoalCreator` i `PromptResponseOptimiser` (segons Liu et al. 2024).  
3. Desar tot l’historial de preguntes i respostes a MongoDB, permetent múltiples fils de treball (cada un identificat per un `context_id`), en un futur per usuari.  
4. Exposar endpoints per:
   - Crear un nou context.  
   - Continuar un context ja iniciat.  
   - Obtenir el context i el prompt generat.  
   - Llistar contextos existents amb filtres per estat o data.  
   - (Opcional) Eliminar contextos en mode `TESTING`.  
5. Integrar-se amb **Policy-Agent**: un cop el prompt de context està llest.



### Requisits previs

1. Docker & Docker Compose (recomanat).
2. Python 3.9+ (si es vol executar sense Docker).
3. Variables d’entorn (fora de Docker, si s’executa localment):

        OPENAI_API_KEY
        MONGO_URI (per exemple, mongodb://localhost:27017/context-agent-db)
        FLASK_SECRET_KEY
        FLASK_ENV: Valor development o production.
        CONFIG_PATH (ruta a context-agent.yaml)

### Configuració

#### Fitxer YAML (context-agent.yaml)
Revisa la carpeta config/exemples/ i utilitza el que et sembli millor, compte! amb CONFIG_PATH

- `questions`: Llista seqüencial de preguntes que es faran a l’usuari. Cada entrada té:

        id: identificador únic de la pregunta (p. ex. country, sector).
        question: text de la qüestió a mostrar.

- `roles`: Seqüència de rols que s’apliquen després de recollir totes les respostes:
 
        name: nom descriptiu (PassiveGoalCreator, etc.).
        type: openai (o mock per a entorn de proves).
        instructions: plantilla textual amb placeholders.
        model: nom del model OpenAI (p. ex. gpt-4o).
        temperature: float (0.0–1.0).
        max_tokens: enter per limitar la resposta.


### Contribució

1. Crea un “fork” del projecte.
2. Clona el teu fork localment.
3. Crea una branca dedicada (p. ex. feat/new-role-evaluation).
4. Fes els teus canvis i executa tots els tests, si crees noves funcions si us plau posa-li un mínim test:
5. Obre un “Pull Request” explicant la funcionalitat o correcció proposada.

### Llicència

Aquest projecte està publicat sota la llicència MIT. Consulta el fitxer LICENSE per a més detalls.