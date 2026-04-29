from pathlib import Path

import yaml


FIXTURE_PATH = Path("tests/fixtures/rag_eval_cases.yaml")


def _load_eval_cases():
    with FIXTURE_PATH.open("r", encoding="utf-8") as fixture_file:
        return yaml.safe_load(fixture_file)


def test_ws8_rag_fixture_catalog_references_context_answer_fixtures():
    catalog = _load_eval_cases()

    for case in catalog["cases"]:
        context_fixture = Path(case["context_fixture"])
        assert context_fixture.parts[-4:] == (
            "config",
            "examples",
            "answers",
            f"{case['id']}.yaml",
        )


def test_ws8_rag_fixture_cases_have_expected_collection_families():
    catalog = _load_eval_cases()

    assert catalog["version"] == 1
    assert len(catalog["cases"]) >= 5

    for case in catalog["cases"]:
        assert case["query_terms"]
        assert set(case["expected_collection_families"]).issubset(
            {"normativa", "sector", "guia", "metodologia"}
        )
        assert "normativa" in case["expected_collection_families"]
