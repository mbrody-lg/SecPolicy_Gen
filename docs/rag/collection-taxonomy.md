# Policy-Agent RAG Collection Taxonomy

## Purpose
Define the target source families used by `policy-agent` RAG. This contributor-facing taxonomy mirrors the local planning guidance in `.local-workspace/strategies/rag/policies/collection_taxonomy.md`.

## Collection Families
| Family | Purpose | Initial Local Source |
| --- | --- | --- |
| `legal_norms` | Legal and regulatory obligations | `policy-agent/data/normativa` |
| `sector_norms` | Sector-specific applicability and constraints | `policy-agent/data/sector` |
| `security_frameworks` | ISO, NIST, CIS, CAF, and equivalent frameworks | `policy-agent/data/metodologia` |
| `risk_methodologies` | Risk analysis methods and asset/risk models | `policy-agent/data/metodologia` |
| `implementation_guides` | Practical controls, checklists, and application guidance | `policy-agent/data/guia` |
| `control_catalog` | Normalized atomic controls | Future derived corpus |
| `business_processes` | Governance and operational process patterns | Future derived corpus |
| `policy_templates` | Approved reusable policy structures | Future curated corpus |
| `validation_criteria` | Evidence-based validation criteria | Future curated corpus |

## Initial Compatibility Rule
`INIT-13` starts by keeping the existing Chroma collection names:
- `normativa`
- `sector`
- `metodologia`
- `guia`

The source manifest maps those names to richer collection families so later work can migrate retrieval behavior without breaking current indexing assumptions.

## Metadata Direction
Every indexed source should move toward metadata that supports strict retrieval:
- collection family and collection name
- source document and section/page when available
- language
- jurisdiction, country, and region
- sector
- framework
- control domain
- asset type
- data type
- applicability
- obligation type
- version/effective date when available

Until metadata-rich indexing lands, the manifest provides source-level defaults.

