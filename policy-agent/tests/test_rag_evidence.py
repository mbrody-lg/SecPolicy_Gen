from app.rag.evidence import RetrievalEvidence, format_evidence_context, normalize_evidence


def test_normalize_evidence_preserves_structured_metadata():
    evidence = normalize_evidence(
        {
            "text": "Article 32 requires appropriate security.",
            "id": "normativa:rgpd:chunk-1",
            "source_id": "normativa",
            "collection": "normativa",
            "family": "legal_norms",
            "score": 0.12,
            "metadata": {"source_doc": "RGPD.pdf"},
        }
    )

    assert evidence == RetrievalEvidence(
        text="Article 32 requires appropriate security.",
        source_id="normativa",
        collection="normativa",
        family="legal_norms",
        document_id="normativa:rgpd:chunk-1",
        score=0.12,
        metadata={"source_doc": "RGPD.pdf"},
    )


def test_normalize_evidence_wraps_legacy_text_results():
    evidence = normalize_evidence("legacy document", fallback_collection="FakeClient")

    assert evidence.text == "legacy document"
    assert evidence.collection == "FakeClient"
    assert evidence.source_id == "legacy"
    assert evidence.citation == "FakeClient:legacy"


def test_format_evidence_context_uses_citeable_blocks():
    context = format_evidence_context(
        [
            RetrievalEvidence(
                text="Use access controls.",
                source_id="guia",
                collection="guia",
                family="implementation_guides",
                document_id="guia:access:chunk-1",
                score=0.2,
            )
        ]
    )

    assert context == (
        "[1] citation=guia:guia:access:chunk-1 "
        "family=implementation_guides score=0.2\n"
        "Use access controls."
    )

