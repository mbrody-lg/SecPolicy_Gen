from pathlib import Path

import pytest

from app.rag.sources import RagSourceManifestError, validate_rag_source_manifest
from scripts import index_pdfs_to_chroma as indexer


def test_load_configs_from_rag_sources_filters_collection():
    configs = indexer.load_configs_from_rag_sources(
        Path("app/config/rag_sources.yaml"),
        collection_filter="metodologia",
    )

    assert [config["source_id"] for config in configs] == [
        "metodologia_frameworks",
        "metodologia_risk",
    ]
    assert {config["family"] for config in configs} == {
        "security_frameworks",
        "risk_methodologies",
    }


def test_discover_files_uses_include_patterns(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "ISO_27001.pdf").write_text("iso", encoding="utf-8")
    (source_dir / "Magerit_Book.pdf").write_text("magerit", encoding="utf-8")
    (source_dir / "ignored.txt").write_text("ignored", encoding="utf-8")

    files = indexer.discover_files(
        {
            "path": str(source_dir),
            "include": ["ISO_*.pdf"],
        }
    )

    assert files == [source_dir / "ISO_27001.pdf"]


def test_build_chunk_id_is_stable_and_scoped():
    chunk_id = indexer.build_chunk_id(
        {"name": "metodologia", "source_id": "metodologia_frameworks"},
        Path("ISO_27001.pdf"),
        3,
    )

    assert chunk_id == "metodologia:metodologia_frameworks:ISO_27001:chunk-3"


def test_build_chunk_metadata_flattens_list_values():
    metadata = indexer.build_chunk_metadata(
        {
            "source_id": "normativa",
            "name": "normativa",
            "family": "legal_norms",
            "metadata": {
                "source_kind": "regulation",
                "jurisdiction": ["EU", "ES"],
                "language": ["es", "ca"],
                "applicability": "legal_obligations",
                "priority": "high",
            },
        },
        Path("RGPD.pdf"),
        2,
    )

    assert metadata == {
        "source_id": "normativa",
        "collection": "normativa",
        "collection_family": "legal_norms",
        "source_doc": "RGPD.pdf",
        "source_stem": "RGPD",
        "chunk_index": 2,
        "source_kind": "regulation",
        "jurisdiction": "EU,ES",
        "language": "es,ca",
        "applicability": "legal_obligations",
        "priority": "high",
    }


def test_process_source_dry_run_does_not_call_chroma(tmp_path, monkeypatch):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "guide.pdf").write_text("pdf placeholder", encoding="utf-8")

    def unexpected_chroma_call(*args, **kwargs):
        raise AssertionError("dry-run should not call Chroma or model loading")

    monkeypatch.setattr(indexer, "_get_chroma_collection", unexpected_chroma_call)

    result = indexer.process_source(
        {
            "source_id": "guia",
            "name": "guia",
            "path": str(source_dir),
            "family": "implementation_guides",
            "metadata": {
                "source_kind": "implementation_guide",
                "jurisdiction": ["ES"],
                "language": ["es"],
                "applicability": "practical_controls",
                "priority": "medium",
            },
            "chunk_size": 300,
            "chunk_overlap": 50,
            "file_types": ["pdf"],
            "model": "test-model",
        },
        dry_run=True,
    )

    assert result == {"indexed": 0, "skipped": 0, "files": 1}


def test_validate_source_configs_checks_paths_without_model_or_indexing(tmp_path, monkeypatch):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "guide.pdf").write_text("pdf placeholder", encoding="utf-8")

    def unexpected_chroma_call(*args, **kwargs):
        raise AssertionError("validate-only should not load models or open collections")

    monkeypatch.setattr(indexer, "_get_chroma_collection", unexpected_chroma_call)

    totals = indexer.validate_source_configs(
        [
            {
                "source_id": "guia",
                "name": "guia",
                "path": str(source_dir),
                "include": None,
                "file_types": ["pdf"],
            }
        ],
        check_chroma=False,
    )

    assert totals == {"sources": 1, "collections": 1, "files": 1}


def test_validate_source_configs_fails_for_missing_source_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="path does not exist"):
        indexer.validate_source_configs(
            [
                {
                    "source_id": "missing",
                    "name": "normativa",
                    "path": str(tmp_path / "missing"),
                    "include": None,
                    "file_types": ["pdf"],
                }
            ],
            check_chroma=False,
        )


def test_validate_source_configs_optionally_checks_chroma(monkeypatch, tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    calls = []

    class FakeChromaClient:
        def __init__(self, host, port):
            calls.append((host, port))

        def heartbeat(self):
            calls.append("heartbeat")

    class FakeChromadb:
        HttpClient = FakeChromaClient

    monkeypatch.setenv("CHROMA_HOST", "chroma")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setattr(indexer, "_get_chromadb", lambda: FakeChromadb)

    totals = indexer.validate_source_configs(
        [
            {
                "source_id": "guia",
                "name": "guia",
                "path": str(source_dir),
                "include": None,
                "file_types": ["pdf"],
            }
        ],
        check_chroma=True,
    )

    assert totals == {"sources": 1, "collections": 1, "files": 0}
    assert calls == [("chroma", 8000), "heartbeat"]


def test_manifest_rejects_invalid_chroma_collection_name():
    manifest = {
        "version": 1,
        "sources": [
            {
                "id": "bad_collection",
                "path": "data/normativa",
                "collection": "bad name",
                "family": "legal_norms",
                "metadata": {
                    "source_kind": "regulation",
                    "jurisdiction": ["ES"],
                    "language": ["es"],
                    "applicability": "legal_obligations",
                    "priority": "high",
                },
            }
        ],
    }

    with pytest.raises(RagSourceManifestError, match="invalid Chroma collection name"):
        validate_rag_source_manifest(manifest)
