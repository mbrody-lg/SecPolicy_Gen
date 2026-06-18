from pathlib import Path

import pytest
import yaml

from app.context_analysis.security_context import (
    REQUIRED_SECTIONS,
    build_security_context_from_answers,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "context_eval_cases.yaml"
CONFIDENCE_ORDER = {
    "very_low": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}
REQUIRED_PATHS = (
    ("profile", "sector"),
    ("profile", "operating_countries"),
    ("information_assets", "critical_assets"),
    ("policy_intent", "need"),
)
POLICY_DRAFT_MARKERS = (
    "policy statement",
    "shall comply",
    "scope of this policy",
    "non-compliance",
    "enforcement",
)


def _load_cases():
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)["cases"]


def _has_value(value):
    if isinstance(value, list):
        return bool(value)
    return value is not None and str(value).strip() != ""


def _required_coverage(context):
    present = 0
    for section, field in REQUIRED_PATHS:
        if _has_value(context[section][field]):
            present += 1
    return present / len(REQUIRED_PATHS)


def _assert_expected_subset(actual, expected):
    missing = set(expected or []) - set(actual or [])
    assert not missing


def _assert_no_policy_draft(context):
    generated_text = "\n".join(
        str(context["policy_intent"].get(field) or "")
        for field in ("need", "policy_type", "scope", "audience")
    ).lower()
    for marker in POLICY_DRAFT_MARKERS:
        assert marker not in generated_text


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_context_agent_deterministic_eval_release_gate(case):
    context = build_security_context_from_answers(
        case["answers"],
        language=case["answers"].get("language", "en"),
    )
    expected = case["expected"]

    assert set(REQUIRED_SECTIONS).issubset(context)
    assert _required_coverage(context) >= expected["required_coverage"]

    if "max_missing" in expected:
        assert len(context["analysis"]["missing_information"]) <= expected["max_missing"]
    if "min_missing" in expected:
        assert len(context["analysis"]["missing_information"]) >= expected["min_missing"]
    if "missing_information" in expected:
        _assert_expected_subset(
            context["analysis"]["missing_information"],
            expected["missing_information"],
        )

    if "confidence_min" in expected:
        assert (
            CONFIDENCE_ORDER[context["analysis"]["confidence"]]
            >= CONFIDENCE_ORDER[expected["confidence_min"]]
        )
    if "confidence_max" in expected:
        assert (
            CONFIDENCE_ORDER[context["analysis"]["confidence"]]
            <= CONFIDENCE_ORDER[expected["confidence_max"]]
        )

    _assert_expected_subset(
        context["information_assets"]["data_categories"],
        expected.get("data_categories", []),
    )
    _assert_expected_subset(
        context["retrieval_hints"]["collection_families"],
        expected.get("collection_families", []),
    )
    _assert_no_policy_draft(context)
