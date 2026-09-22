from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_dependency_maintenance_report import build_report, runtime_status, write_report


def test_runtime_status_is_deterministic():
    assert runtime_status(date(2025, 10, 31), date(2026, 9, 22), 180) == "eol"
    assert runtime_status(date(2026, 10, 31), date(2026, 9, 22), 180) == "approaching_eol"
    assert runtime_status(date(2027, 10, 31), date(2026, 9, 22), 180) == "supported"


def test_report_inventories_repository_and_writes_artifacts(tmp_path):
    report = build_report(date(2026, 9, 22))
    write_report(report, tmp_path)

    assert report["summary"]["eol_runtimes"] == 1
    assert report["summary"]["approaching_eol_runtimes"] == 1
    assert {item["name"] for item in report["python_requirements"]} >= {"Flask", "openai"}
    assert any(item["name"] == "@playwright/test" for item in report["node_packages"])
    assert json.loads((tmp_path / "dependency-maintenance.json").read_text())["generated_on"] == "2026-09-22"
    assert "Python" not in (tmp_path / "dependency-maintenance.md").read_text()
