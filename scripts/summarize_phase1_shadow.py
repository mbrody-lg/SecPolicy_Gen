#!/usr/bin/env python3
"""Summarize per-case Phase 1 shadow comparison artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_case_result(case_dir: Path) -> dict:
    compare_file = case_dir / "compare-output.json"
    candidate_file = case_dir / "candidate-output.json"
    legacy_file = case_dir / "legacy-output.json"

    result = {
        "case_dir": str(case_dir),
        "case_name": case_dir.name,
        "legacy_present": legacy_file.exists(),
        "candidate_present": candidate_file.exists(),
        "compare_present": compare_file.exists(),
        "contract_compatible": False,
        "difference_count": None,
        "candidate_status": None,
        "legacy_status": None,
        "error": None,
    }

    if not compare_file.exists():
      result["error"] = "missing_compare_output"
      return result

    try:
        compare = _load_json(compare_file)
    except Exception as exc:  # pragma: no cover - defensive summary path
        result["error"] = f"invalid_compare_output:{exc}"
        return result

    if "error" in compare:
        result["error"] = compare["error"]
        return result

    result["contract_compatible"] = bool(compare.get("contract_compatible"))
    result["difference_count"] = len(compare.get("value_differences", []))

    if candidate_file.exists():
        try:
            candidate = _load_json(candidate_file)
            result["candidate_status"] = candidate.get("status")
        except Exception as exc:  # pragma: no cover - defensive summary path
            result["error"] = f"invalid_candidate_output:{exc}"

    if legacy_file.exists():
        try:
            legacy = _load_json(legacy_file)
            result["legacy_status"] = legacy.get("status")
        except Exception as exc:  # pragma: no cover - defensive summary path
            result["error"] = f"invalid_legacy_output:{exc}"

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Summarize the artifacts produced by Phase 1 shadow-mode runs."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory that contains one subdirectory per golden case shadow run.",
    )
    args = parser.parse_args()

    root = Path(args.input_dir)
    if not root.is_dir():
        raise SystemExit(f"Input directory not found: {root}")

    case_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    per_case = [_collect_case_result(case_dir) for case_dir in case_dirs]

    compatible_cases = [item for item in per_case if item["contract_compatible"]]
    comparable_cases = [item for item in per_case if item["compare_present"]]
    failed_cases = [item for item in per_case if item["error"] or not item["contract_compatible"]]

    summary = {
        "input_dir": str(root),
        "total_case_dirs": len(case_dirs),
        "comparable_cases": len(comparable_cases),
        "contract_compatible_cases": len(compatible_cases),
        "failed_cases": len(failed_cases),
        "cases": per_case,
    }

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
