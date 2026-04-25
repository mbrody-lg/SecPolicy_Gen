from pathlib import Path

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

