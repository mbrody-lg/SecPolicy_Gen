"""Structured retrieval evidence helpers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalEvidence:
    """One retrieved evidence chunk."""

    text: str
    source_id: str
    collection: str
    family: str | None = None
    document_id: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        """Return a stable citation label for prompt grounding."""
        if self.document_id:
            return f"{self.collection}:{self.document_id}"
        return f"{self.collection}:{self.source_id}"


def normalize_evidence(raw_item: Any, *, fallback_collection: str = "unknown") -> RetrievalEvidence:
    """Normalize vector client output into RetrievalEvidence."""
    if isinstance(raw_item, RetrievalEvidence):
        return raw_item
    if isinstance(raw_item, dict):
        metadata = raw_item.get("metadata") if isinstance(raw_item.get("metadata"), dict) else {}
        collection = str(raw_item.get("collection") or metadata.get("collection") or fallback_collection)
        return RetrievalEvidence(
            text=str(raw_item.get("text") or raw_item.get("document") or ""),
            source_id=str(raw_item.get("source_id") or metadata.get("source_id") or "unknown"),
            collection=collection,
            family=raw_item.get("family") or metadata.get("collection_family"),
            document_id=raw_item.get("document_id") or raw_item.get("id"),
            score=raw_item.get("score"),
            metadata=metadata,
        )
    return RetrievalEvidence(
        text=str(raw_item),
        source_id="legacy",
        collection=fallback_collection,
    )


def format_evidence_context(evidence_items: list[RetrievalEvidence]) -> str:
    """Format retrieved evidence as citeable prompt blocks."""
    blocks = []
    for index, evidence in enumerate(evidence_items, start=1):
        header = f"[{index}] citation={evidence.citation}"
        if evidence.family:
            header += f" family={evidence.family}"
        if evidence.score is not None:
            header += f" score={evidence.score}"
        blocks.append(f"{header}\n{evidence.text}")
    return "\n\n".join(blocks)

