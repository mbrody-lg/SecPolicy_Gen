# Policy-Agent RAG Current State

## Purpose
Capture the baseline before `INIT-13` changes the retrieval architecture.

## Current Flow
1. `context-agent` sends `context_id`, `refined_prompt`, `language`, and `model_version` to `policy-agent`.
2. `policy-agent` validates the request in `app/services/logic.py`.
3. `policy-agent` creates the configured agent from `app/config/policy_agent.yaml`.
4. The OpenAI agent executes role order from YAML.
5. The `RAG` role instantiates `RAGProcessor`.
6. `RAGProcessor` loads configured Chroma vector clients and searches them with one natural-language query.
7. Retrieved document text is appended to the prompt under `=== Relevant Context ===`.
8. Later roles generate, refine, and return the policy text.

## Active Configuration Baseline
The active YAML baseline uses:
- backend: Chroma
- embedding model: `intfloat/e5-base`
- model revision: `b533fe4636f4a2507c08ddab40644d20b0006d6a`
- chunk size: `300`
- chunk overlap: `50`
- active collection before `INIT-13`: `legal_norms`

## Local Source Inventory
Current source folders under `policy-agent/data/`:

| Folder | Approximate Role | Current Files | Notes |
| --- | --- | ---: | --- |
| `legal_norms` | legal and regulatory sources | 7 PDFs | GDPR/RGPD, LOPDGDD, LSSI-CE, breach notification guidance, copyright/marks |
| `sector_norms` | sector-specific guidance | 11 PDFs | ecommerce, retail, construction, education, health, industry, logistics, tourism, professional services |
| `security_frameworks` | frameworks | 5 PDFs | ISO 27001/27002, CIS, NIST CSF, UK CAF |
| `risk_methodologies` | risk methodologies | 3 PDFs | MAGERIT method, catalogue, and techniques |
| `implementation_guides` | implementation guides and checklists | 34 PDFs | access control, backups, logs, telework, encryption, suppliers, HR, awareness, ecommerce, secure deletion |

The `CONTENT.TXT` files are useful rough manifests but are not authoritative. Some entries are stale or inconsistent with actual filenames.

## Known Limitations
- The RAG role currently uses one broad query rather than a structured retrieval plan.
- The active configuration previously queried only `legal_norms`, leaving
  `sector_norms`, `security_frameworks`, `risk_methodologies`, and `implementation_guides` sources unused by default.
- Indexed chunks do not yet carry enough metadata for strict filtering by jurisdiction, sector, framework, data type, asset type, or applicability.
- Vector search currently returns plain document text to the RAG processor, not source ids, metadata, scores, or collection names.
- The generated policy does not persist retrieval evidence or citations.
- There is no retrieval evaluation dataset yet.

## First Modernization Slice
The first `INIT-13` slice keeps runtime behavior conservative:
- document the baseline
- introduce a source manifest
- validate manifest shape
- configure existing collections for multi-collection retrieval
- add tests around configuration and manifest loading

Later slices should add metadata-rich indexing, query planning, structured evidence, reranking, evidence persistence, validator grounding, and RAG evaluation.
