#!/usr/bin/env python3
"""Validate the repository contract for Context Agent frontend dependencies."""

import argparse
import json
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "context-agent" / "frontend"
PACKAGE_JSON_PATH = FRONTEND_DIR / "package.json"
PNPM_LOCK_PATH = FRONTEND_DIR / "pnpm-lock.yaml"
FORBIDDEN_LOCKFILES = (
    FRONTEND_DIR / "package-lock.json",
    FRONTEND_DIR / "npm-shrinkwrap.json",
    FRONTEND_DIR / "yarn.lock",
)
PACKAGE_MANAGER_PATTERN = re.compile(r"^pnpm@(?P<version>\d+\.\d+\.\d+)$")
FORBIDDEN_NPM_COMMAND = re.compile(r"\b(?:npm\s+(?:ci|install|run)|npx)\b")


def package_manager_version() -> str:
    """Return the exact pnpm version declared by the frontend manifest."""
    manifest = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    package_manager = manifest.get("packageManager", "")
    match = PACKAGE_MANAGER_PATTERN.fullmatch(package_manager)
    if not match:
        raise ValueError("packageManager must use the exact form pnpm@x.y.z")
    return match.group("version")


def command_contract_paths() -> list[Path]:
    """Return active files where frontend package-manager commands may live."""
    paths = [
        ROOT_DIR / "Makefile",
        ROOT_DIR / "README.md",
        ROOT_DIR / "CONTRIBUTING.md",
        ROOT_DIR / "context-agent" / "README.md",
    ]
    paths.extend((ROOT_DIR / "docs").rglob("*.md"))
    paths.extend((ROOT_DIR / ".github" / "workflows").glob("*.yml"))
    paths.extend((ROOT_DIR / ".github" / "workflows").glob("*.yaml"))
    paths.extend(
        path
        for path in (ROOT_DIR / "scripts").glob("*")
        if path.is_file() and path != Path(__file__)
    )
    return [path for path in paths if path.is_file()]


def validate_contract() -> list[str]:
    """Return all package-manager governance violations."""
    violations = []
    try:
        package_manager_version()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        violations.append(str(exc))

    if not PNPM_LOCK_PATH.is_file():
        violations.append("context-agent/frontend/pnpm-lock.yaml is required")

    for path in FORBIDDEN_LOCKFILES:
        if path.exists():
            violations.append(f"forbidden lockfile: {path.relative_to(ROOT_DIR)}")

    for path in command_contract_paths():
        if FORBIDDEN_NPM_COMMAND.search(path.read_text(encoding="utf-8")):
            violations.append(
                f"forbidden npm command: {path.relative_to(ROOT_DIR)}"
            )

    workflow_path = ROOT_DIR / ".github" / "workflows" / "frontend.yml"
    if not workflow_path.is_file():
        violations.append(".github/workflows/frontend.yml is required")
        return violations

    workflow_text = workflow_path.read_text(encoding="utf-8")
    makefile_text = (ROOT_DIR / "Makefile").read_text(encoding="utf-8")
    required_contracts = (
        (
            workflow_text,
            re.compile(
                r"(?m)^\s+package_json_file:\s+"
                r"context-agent/frontend/package\.json\s*$"
            ),
            "pnpm setup must read context-agent/frontend/package.json",
        ),
        (
            workflow_text,
            re.compile(r"(?m)^\s+run:\s+make frontend-check\s*$"),
            "frontend workflow must run make frontend-check",
        ),
        (
            makefile_text,
            re.compile(
                r"(?m)^\s+cd \$\(FRONTEND_DIR\) && "
                r"\$\(PNPM_COMMAND\) install --frozen-lockfile\s*$"
            ),
            "frontend install must use --frozen-lockfile",
        ),
    )
    for source, pattern, description in required_contracts:
        if not pattern.search(source):
            violations.append(f"missing package-manager contract: {description}")

    return violations


def main() -> int:
    """Validate the contract or print the pinned pnpm version."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-version", action="store_true")
    args = parser.parse_args()

    if args.print_version:
        try:
            print(package_manager_version())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    violations = validate_contract()
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1

    print("Frontend package-manager contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
