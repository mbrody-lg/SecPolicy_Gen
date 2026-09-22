from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.validate_python_support import load_policy, validate_repository, workflow_versions


def test_python_support_policy_matches_repository_contract():
    assert validate_repository(date(2026, 9, 22)) == []


def test_required_matrix_excludes_eol_and_preview_versions():
    policy = load_policy()

    assert workflow_versions() == ["3.11", "3.12", "3.13", "3.14"]
    assert "3.9" not in policy["supported_runtime_versions"]
    assert policy["compatibility_target_versions"] == ["3.12", "3.13", "3.14"]
    assert "3.15" in policy["preview_versions"]
