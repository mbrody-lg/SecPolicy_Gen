#!/usr/bin/env python3
"""Validate the repository Python support and end-of-life contract."""

from datetime import date
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / ".github" / "python-support-policy.json"
SERVICES = ("context-agent", "policy-agent", "validator-agent")


def load_policy() -> dict:
    """Load the canonical Python support policy."""
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def workflow_versions() -> list[str]:
    """Read the required Python versions from the Pylint workflow matrix."""
    workflow = (ROOT / ".github" / "workflows" / "pylint.yml").read_text(encoding="utf-8")
    match = re.search(r"python-version:\s*\[([^]]+)]", workflow)
    if not match:
        return []
    return re.findall(r'"(\d+\.\d+)"', match.group(1))


def validate_repository(today: date | None = None) -> list[str]:
    """Return violations of the support matrix and EOL policy."""
    policy = load_policy()
    today = today or date.today()
    supported = policy["supported_runtime_versions"]
    compatibility_targets = policy["compatibility_target_versions"]
    preview = policy["preview_versions"]
    baseline = policy["baseline_version"]
    errors = []

    if len(supported) != len(set(supported)):
        errors.append("supported_versions contains duplicates")
    if baseline not in supported:
        errors.append("baseline_version must be supported")
    if set(compatibility_targets) & set(supported):
        errors.append("compatibility targets cannot already be supported runtimes")
    if set(preview) & (set(supported) | set(compatibility_targets)):
        errors.append("preview versions must be separate from runtime and compatibility tiers")

    version_entries = {item["version"]: item for item in policy["versions"]}
    governed_versions = set(supported) | set(compatibility_targets) | set(preview)
    missing_entries = sorted(governed_versions - set(version_entries))
    if missing_entries:
        errors.append(f"versions missing lifecycle entries: {missing_entries}")

    eol_supported = sorted(
        version
        for version in supported
        if version in version_entries and today > date.fromisoformat(version_entries[version]["eol"])
    )
    if eol_supported:
        errors.append(f"end-of-life versions cannot remain supported: {eol_supported}")

    if workflow_versions() != supported + compatibility_targets:
        errors.append("Pylint matrix must cover supported runtimes and compatibility targets")

    expected_from = f"FROM python:{baseline}-slim"
    expected_constraints = f"constraints-py{baseline.replace('.', '')}.txt"
    for service in SERVICES:
        dockerfile = (ROOT / service / "Dockerfile").read_text(encoding="utf-8")
        if expected_from not in dockerfile:
            errors.append(f"{service}: Docker baseline differs from {baseline}")
        if expected_constraints not in dockerfile:
            errors.append(f"{service}: constraints do not match baseline {baseline}")

    return errors


def main() -> int:
    """Print violations and return non-zero when the contract is invalid."""
    errors = validate_repository()
    if errors:
        print("\n".join(errors))
        return 1
    print("Python support and EOL policy are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
