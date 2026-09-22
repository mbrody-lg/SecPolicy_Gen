#!/usr/bin/env python3
"""Build a deterministic, informational dependency-maintenance report."""

import argparse
from datetime import date
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".github" / "dependency-maintenance-policy.json"
REQUIREMENTS = [ROOT / name / "requirements.txt" for name in ("context-agent", "policy-agent", "validator-agent")]
PACKAGES = [ROOT / "context-agent/frontend/package.json", ROOT / "tests/browser/package.json"]


def runtime_status(eol: date, today: date, warning_days: int) -> str:
    if today > eol:
        return "eol"
    if (eol - today).days <= warning_days:
        return "approaching_eol"
    return "supported"


def requirement_inventory() -> list[dict]:
    result = []
    for path in REQUIREMENTS:
        for raw in path.read_text(encoding="utf-8").splitlines():
            value = raw.split("#", 1)[0].strip()
            if not value:
                continue
            match = re.match(r"^([A-Za-z0-9_.-]+)(.*)$", value)
            name, specifier = match.groups()
            result.append({"file": str(path.relative_to(ROOT)), "name": name, "specifier": specifier or None,
                           "constraint": "exact" if "==" in specifier else "bounded" if "<" in specifier else "minimum" if ">=" in specifier else "unbounded"})
    return result


def package_inventory() -> list[dict]:
    result = []
    for path in PACKAGES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for group in ("dependencies", "devDependencies"):
            for name, specifier in sorted(payload.get(group, {}).items()):
                result.append({"file": str(path.relative_to(ROOT)), "group": group, "name": name, "specifier": specifier})
    return result


def reference_inventory() -> dict[str, list[dict]]:
    images, actions = [], []
    for path in list(ROOT.rglob("Dockerfile")) + [ROOT / "infrastructure/docker-compose.yml"]:
        for raw in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:FROM|image:)\s+([^\s]+)", raw)
            if match:
                ref = match.group(1)
                images.append({"file": str(path.relative_to(ROOT)), "reference": ref, "digest_pinned": "@sha256:" in ref})
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        for ref in re.findall(r"uses:\s*([^\s#]+)", path.read_text(encoding="utf-8")):
            version = ref.rsplit("@", 1)[-1]
            actions.append({"file": str(path.relative_to(ROOT)), "reference": ref, "commit_pinned": bool(re.fullmatch(r"[0-9a-f]{40}", version))})
    return {"container_images": images, "github_actions": actions}


def build_report(today: date) -> dict:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    warning_days = policy["warning_window_days"]
    runtimes = []
    for item in policy["runtimes"]:
        entry = dict(item)
        entry["status"] = runtime_status(date.fromisoformat(item["eol"]), today, warning_days)
        entry["source"] = policy["sources"][item["name"]]
        runtimes.append(entry)
    refs = reference_inventory()
    requirements = requirement_inventory()
    return {"schema_version": policy["schema_version"], "generated_on": today.isoformat(), "runtimes": runtimes,
            "python_requirements": requirements, "node_packages": package_inventory(), **refs,
            "summary": {"eol_runtimes": sum(x["status"] == "eol" for x in runtimes),
                        "approaching_eol_runtimes": sum(x["status"] == "approaching_eol" for x in runtimes),
                        "unbounded_python_requirements": sum(x["constraint"] == "unbounded" for x in requirements),
                        "unpinned_container_images": sum(not x["digest_pinned"] for x in refs["container_images"]),
                        "unpinned_github_actions": sum(not x["commit_pinned"] for x in refs["github_actions"])}}


def write_report(report: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dependency-maintenance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Dependency Maintenance Report", "", f"Generated: {report['generated_on']}", "", "## Runtime lifecycle", "", "| Runtime | Version | EOL | Status | Usage |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {x['name']} | {x['version']} | {x['eol']} | {x['status']} | {x['usage']} |" for x in report["runtimes"]]
    lines += ["", "## Summary", ""] + [f"- {key}: `{value}`" for key, value in report["summary"].items()]
    (output_dir / "dependency-maintenance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "migration/dependency-maintenance")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    write_report(build_report(args.today), args.output_dir)


if __name__ == "__main__":
    main()
