from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.validate_python_constraints import canonical_name, validate_repository


def test_canonical_name_normalizes_python_distribution_names():
    assert canonical_name("Flask-PyMongo>=3") == "flask-pymongo"
    assert canonical_name("prometheus_client==0.26.0") == "prometheus-client"


def test_repository_python_constraints_are_complete_and_consumed():
    assert validate_repository() == []
