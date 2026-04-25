"""Deterministic retrieval planning for policy-agent RAG."""

from dataclasses import dataclass, field
from typing import Any

from app.rag.context import RetrievalContext
from app.rag.sources import get_sources_by_family


@dataclass(frozen=True)
class RetrievalPlanStep:
    """One collection query planned for RAG retrieval."""

    family: str
    collection: str
    query: str
    filters: dict[str, Any] = field(default_factory=dict)
    top_k: int = 3


@dataclass(frozen=True)
class RetrievalPlan:
    """A deterministic retrieval plan built from company context."""

    context_id: str
    steps: list[RetrievalPlanStep]
    required_families: list[str]
    coverage_notes: list[str] = field(default_factory=list)


def build_retrieval_plan(context: RetrievalContext, manifest: dict[str, Any]) -> RetrievalPlan:
    """Build collection-specific queries and metadata filters."""
    sources_by_family = get_sources_by_family(manifest)
    required_families = _required_families(context)
    steps: list[RetrievalPlanStep] = []
    coverage_notes: list[str] = []

    for family in required_families:
        sources = sources_by_family.get(family, [])
        if not sources:
            coverage_notes.append(f"missing_source_family:{family}")
            continue
        for source in sources:
            steps.append(
                RetrievalPlanStep(
                    family=family,
                    collection=source["collection"],
                    query=_build_query(context, family),
                    filters=_build_filters(context, source),
                    top_k=_top_k_for_family(family),
                )
            )

    return RetrievalPlan(
        context_id=context.context_id,
        steps=steps,
        required_families=required_families,
        coverage_notes=coverage_notes,
    )


def _required_families(context: RetrievalContext) -> list[str]:
    families = ["legal_norms", "implementation_guides"]
    if context.sector:
        families.append("sector_norms")
    if context.methodology:
        families.append("security_frameworks")
    if context.critical_assets or "risk" in context.refined_prompt.lower():
        families.append("risk_methodologies")
    return families


def _build_query(context: RetrievalContext, family: str) -> str:
    terms = [
        context.need,
        context.sector,
        context.country,
        context.region,
        context.methodology,
        " ".join(context.critical_assets),
        " ".join(context.important_assets),
        " ".join(context.data_types),
    ]
    base_query = " ".join(term for term in terms if term)
    if not base_query:
        base_query = context.refined_prompt
    return f"{family}: {base_query}".strip()


def _build_filters(context: RetrievalContext, source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata", {})
    filters: dict[str, Any] = {
        "collection_family": source["family"],
    }
    if context.country and context.country.upper() in {"SPAIN", "ES"}:
        filters["jurisdiction"] = "ES"
    elif metadata.get("jurisdiction"):
        filters["jurisdiction"] = metadata["jurisdiction"][0]
    if context.language:
        filters["language"] = context.language
    return filters


def _top_k_for_family(family: str) -> int:
    if family == "legal_norms":
        return 4
    if family == "sector_norms":
        return 3
    return 2

