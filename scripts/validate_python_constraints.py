#!/usr/bin/env python3
"""Validate the per-service Python dependency constraint contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("context-agent", "policy-agent", "validator-agent")
NAME_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)")
PIN_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+==[^=<>!~]+$")


def canonical_name(requirement: str) -> str:
    """Return the normalized distribution name at the start of a requirement."""
    match = NAME_PATTERN.match(requirement.strip())
    if not match:
        raise ValueError(f"Cannot parse requirement: {requirement!r}")
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def dependency_lines(path: Path) -> list[str]:
    """Read non-empty, non-comment dependency lines."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate_service(service: str) -> list[str]:
    """Return contract violations for one service."""
    service_dir = ROOT / service
    requirements = dependency_lines(service_dir / "requirements.txt")
    constraints = dependency_lines(service_dir / "constraints-py311.txt")
    constrained_names = {canonical_name(line) for line in constraints}
    errors = []

    unpinned = [line for line in constraints if not PIN_PATTERN.fullmatch(line)]
    if unpinned:
        errors.append(f"{service}: constraints must use exact pins: {unpinned}")

    missing = sorted(
        canonical_name(line)
        for line in requirements
        if canonical_name(line) not in constrained_names
    )
    if missing:
        errors.append(f"{service}: direct requirements missing from constraints: {missing}")

    dockerfile = (service_dir / "Dockerfile").read_text(encoding="utf-8")
    if "-c constraints-py311.txt -r requirements.txt" not in dockerfile:
        errors.append(f"{service}: Dockerfile does not install through constraints")
    if "pip check" not in dockerfile:
        errors.append(f"{service}: Dockerfile does not run pip check")

    return errors


def validate_repository() -> list[str]:
    """Return all repository constraint contract violations."""
    errors = [error for service in SERVICES for error in validate_service(service)]
    policy_constraints = dependency_lines(ROOT / "policy-agent" / "constraints-py311.txt")
    torch_pins = [line for line in policy_constraints if canonical_name(line) == "torch"]
    policy_dockerfile = (ROOT / "policy-agent" / "Dockerfile").read_text(encoding="utf-8")
    if len(torch_pins) != 1 or not torch_pins[0].endswith("+cpu"):
        errors.append("policy-agent: Torch must have one explicit +cpu constraint")
    else:
        torch_version = torch_pins[0].split("==", 1)[1]
        if f"ARG TORCH_VERSION={torch_version}" not in policy_dockerfile:
            errors.append("policy-agent: Dockerfile Torch version differs from constraints")
    if "https://download.pytorch.org/whl/cpu" not in policy_dockerfile:
        errors.append("policy-agent: Dockerfile must use the official Torch CPU index")
    return errors


def main() -> int:
    """Print violations and return a non-zero status when validation fails."""
    errors = validate_repository()
    if errors:
        print("\n".join(errors))
        return 1
    print("Python dependency constraints are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
