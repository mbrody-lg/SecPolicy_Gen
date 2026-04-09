#!/usr/bin/env python3
"""Summarize per-case Phase 1 shadow comparison artifacts."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
        "difference_fields": [],
        "candidate_status": None,
        "legacy_status": None,
        "strategy_id": None,
        "case_id": None,
        "error": None,
    }

    if not compare_file.exists():
      result["error"] = "missing_compare_output"
    if candidate_file.exists():
        try:
            candidate = _load_json(candidate_file)
            result["candidate_status"] = candidate.get("status")
            result["case_id"] = candidate.get("case_id", result["case_id"])
            result["strategy_id"] = candidate.get("strategy_id", result["strategy_id"])
        except Exception as exc:  # pragma: no cover - defensive summary path
            result["error"] = f"invalid_candidate_output:{exc}"

    if legacy_file.exists():
        try:
            legacy = _load_json(legacy_file)
            result["legacy_status"] = legacy.get("status")
            result["case_id"] = legacy.get("case_id", result["case_id"])
            result["strategy_id"] = legacy.get("strategy_id", result["strategy_id"])
        except Exception as exc:  # pragma: no cover - defensive summary path
            result["error"] = f"invalid_legacy_output:{exc}"

    if not compare_file.exists():
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
    result["difference_fields"] = [
        item.get("field") for item in compare.get("value_differences", []) if item.get("field")
    ]

    return result


def _aggregate_by_strategy(per_case: list[dict]) -> dict:
    grouped = defaultdict(list)
    for item in per_case:
        grouped[item.get("strategy_id") or "unknown"].append(item)

    strategy_summary = {}
    for strategy_id, items in sorted(grouped.items()):
        strategy_summary[strategy_id] = {
            "cases": len(items),
            "contract_compatible_cases": sum(1 for item in items if item["contract_compatible"]),
            "failed_cases": sum(1 for item in items if item["error"]),
            "legacy_statuses": dict(Counter(item["legacy_status"] for item in items if item["legacy_status"])),
            "candidate_statuses": dict(Counter(item["candidate_status"] for item in items if item["candidate_status"])),
        }
    return strategy_summary


def _build_markdown_report(summary: dict) -> str:
    lines = [
        "# Phase 1 Shadow Summary",
        "",
        f"- Input directory: `{summary['input_dir']}`",
        f"- Total case dirs: `{summary['total_case_dirs']}`",
        f"- Comparable cases: `{summary['comparable_cases']}`",
        f"- Contract-compatible cases: `{summary['contract_compatible_cases']}`",
        f"- Failed cases: `{summary['failed_cases']}`",
        "",
        "## Divergence By Field",
    ]

    field_counts = summary["field_difference_counts"]
    if field_counts:
        for field, count in sorted(field_counts.items()):
            lines.append(f"- `{field}`: {count}")
    else:
        lines.append("- No value differences recorded.")

    lines.extend(["", "## By Strategy"])
    for strategy_id, item in summary["strategy_breakdown"].items():
        lines.append(
            f"- `{strategy_id}`: cases={item['cases']}, "
            f"contract_compatible={item['contract_compatible_cases']}, failed={item['failed_cases']}"
        )

    lines.extend(["", "## Case Details"])
    for item in summary["cases"]:
        detail = (
            f"- `{item['case_name']}`"
            f" strategy=`{item['strategy_id'] or 'unknown'}`"
            f" legacy_status=`{item['legacy_status'] or 'n/a'}`"
            f" candidate_status=`{item['candidate_status'] or 'n/a'}`"
            f" compatible=`{item['contract_compatible']}`"
            f" diff_count=`{item['difference_count']}`"
        )
        if item["error"]:
            detail += f" error=`{item['error']}`"
        lines.append(detail)

    return "\n".join(lines) + "\n"


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
    field_difference_counts = Counter()
    for item in per_case:
        field_difference_counts.update(item["difference_fields"])

    summary = {
        "input_dir": str(root),
        "total_case_dirs": len(case_dirs),
        "comparable_cases": len(comparable_cases),
        "contract_compatible_cases": len(compatible_cases),
        "failed_cases": len(failed_cases),
        "field_difference_counts": dict(sorted(field_difference_counts.items())),
        "strategy_breakdown": _aggregate_by_strategy(per_case),
        "cases": per_case,
    }
    markdown_report = _build_markdown_report(summary)
    summary["markdown_report"] = markdown_report

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
