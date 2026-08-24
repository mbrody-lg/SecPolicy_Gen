import json
from pathlib import Path

import pytest

from scripts.build_execution_baseline import (
    DEFAULT_CONFIG_PATH,
    DeterministicProvider,
    build_execution_baseline,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "policy_execution_baseline.json"


def test_policy_execution_baseline_is_reproducible():
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    first = build_execution_baseline(DEFAULT_CONFIG_PATH)
    second = build_execution_baseline(DEFAULT_CONFIG_PATH)

    assert first == second == expected
    assert first["generation"]["logical_calls"] == 5
    assert first["update"]["logical_calls"] == 1
    assert first["generation"]["configured_output_token_ceiling"] == 55_000
    assert first["update"]["configured_output_token_ceiling"] == 15_000


def test_deterministic_provider_captures_failure_category():
    provider = DeterministicProvider(["unused"], failure_categories={1: "timeout"})

    with pytest.raises(RuntimeError, match="timeout"):
        provider.chat.completions.create(
            model="baseline-model",
            messages=[{"role": "user", "content": "baseline"}],
            temperature=0,
            max_tokens=10,
        )

    assert provider.calls[0]["failure_category"] == "timeout"
    assert provider.calls[0]["messages"][0]["content"] == "baseline"
