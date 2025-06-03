# Projecte Multiagent de Generació i Validació de Polítiques de Seguretat

## Descripció

Aquest projecte és un sistema modular de microserveis que utilitza Intel·ligència Artificial per:
1. **Generar context** a partir de preguntes a l’usuari.
2. **Crear polítiques de seguretat** basades en normes (ISO 27001, GDPR, etc.) i dades normatives.
3. **Validar i revisar** les polítiques generades mitjançant consens entre agents especialitzats.

Està compost per tres agents principals:
- **Context‐Agent**: Gestiona la interacció amb l’usuari per capturar informació contextual mitjançant formularis i wizard.
- **Policy‐Agent**: Aplica patrons de Retrieval‐Augmented Generation (RAG) per elaborar una proposta de política de seguretat segons el context i els conjunts de dades normatives.
- **Validator‐Agent**: Executa múltiples rodes de validació (consens) entre sub‐agents responsables de diferents aspectes (compliment, lògica, to, etc.) i, si cal, demana revisions fins a 3 rondes.

Cada agent és un servei Flask que:
- Llegeix una configuració YAML de rols (patterns de Liu et al. 2024: PassiveGoalCreator, ProactiveGoalCreator, PromptResponseOptimiser, RAG, etc.).
- Interactua amb una base de dades (MongoDB) per persistir estats, contextos i resultats.
- Utilitza un client HTTP per accedir a un servei Chroma (base de dades vectorial) en mode RAG.
- Pot fer servir OpenAI (via SDK en beta) o MockAgent per a proves locals.

---

## Enllaços als README dels Subprojectes

- [infrastructure/README.md](infrastructure/README.md)  
- [context-agent/README.md](context-agent/README.md)  
- [policy-agent/README.md](policy-agent/README.md)  
- [validator-agent/README.md](validator-agent/README.md)  

---
