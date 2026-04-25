from pathlib import Path

import pytest

from app.rag.sources import (
    RagSourceManifestError,
    get_manifest_collections,
    load_rag_source_manifest,
    validate_rag_source_manifest,
)


def test_load_rag_source_manifest_exposes_current_collections():
    manifest = load_rag_source_manifest(Path("app/config/rag_sources.yaml"))

    assert get_manifest_collections(manifest) == ["normativa", "sector", "metodologia", "guia"]
    assert {source["family"] for source in manifest["sources"]} == {
        "legal_norms",
        "sector_norms",
        "security_frameworks",
        "risk_methodologies",
        "implementation_guides",
    }


def test_validate_rag_source_manifest_rejects_missing_metadata():
    manifest = {
        "version": 1,
        "sources": [
            {
                "id": "broken",
                "path": "data/broken",
                "collection": "broken",
                "family": "legal_norms",
                "metadata": {
                    "source_kind": "regulation",
                    "jurisdiction": ["EU"],
                    "language": ["en"],
                },
            }
        ],
    }

    with pytest.raises(RagSourceManifestError, match="missing required fields"):
        validate_rag_source_manifest(manifest)


def test_validate_rag_source_manifest_rejects_duplicate_source_ids():
    manifest = {
        "version": 1,
        "sources": [
            {
                "id": "duplicate",
                "path": "data/a",
                "collection": "a",
                "family": "legal_norms",
                "metadata": {
                    "source_kind": "regulation",
                    "jurisdiction": ["EU"],
                    "language": ["en"],
                    "applicability": "legal_obligations",
                    "priority": "high",
                },
            },
            {
                "id": "duplicate",
                "path": "data/b",
                "collection": "b",
                "family": "sector_norms",
                "metadata": {
                    "source_kind": "sector_guidance",
                    "jurisdiction": ["ES"],
                    "language": ["es"],
                    "applicability": "sector_context",
                    "priority": "medium",
                },
            },
        ],
    }

    with pytest.raises(RagSourceManifestError, match="duplicated"):
        validate_rag_source_manifest(manifest)

