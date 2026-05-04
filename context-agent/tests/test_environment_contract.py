"""Static coverage checks for the INIT-02 environment contract."""

import re
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT_DIR / "docs" / "playbooks" / "environment-configuration.md"

CONTRACT_VARIABLE_PATTERN = re.compile(r"`([A-Z][A-Z0-9_]+)`")
PYTHON_ENV_PATTERN = re.compile(
    r"(?:os\.getenv|os\.environ(?:\.get|\.setdefault)?|"
    r"_get_env_(?:bool|int|float|list))\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"
)
PYTHON_ENV_ASSIGN_PATTERN = re.compile(
    r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]"
)
SHELL_ENV_DEFAULT_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-")
COMPOSE_ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
DOCKER_ENV_PATTERN = re.compile(r"^\s*ENV\s+([A-Z][A-Z0-9_]*)=", re.MULTILINE)

PYTHON_SCAN_PATHS = [
    ROOT_DIR / "context-agent" / "app",
    ROOT_DIR / "context-agent" / "generate_context_from_yaml.py",
    ROOT_DIR / "policy-agent" / "app",
    ROOT_DIR / "policy-agent" / "scripts",
    ROOT_DIR / "validator-agent" / "app",
]
SHELL_SCAN_PATHS = [
    ROOT_DIR / "scripts",
]
COMPOSE_SCAN_PATHS = [
    ROOT_DIR / "infrastructure" / "docker-compose.yml",
]
DOCKERFILE_PATHS = [
    ROOT_DIR / "context-agent" / "Dockerfile",
    ROOT_DIR / "policy-agent" / "Dockerfile",
    ROOT_DIR / "validator-agent" / "Dockerfile",
]


def _iter_files(path: Path, suffixes: tuple[str, ...]):
    if path.is_file():
        yield path
        return

    for suffix in suffixes:
        yield from path.rglob(f"*{suffix}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contract_variables() -> set[str]:
    return set(CONTRACT_VARIABLE_PATTERN.findall(_read(CONTRACT_PATH)))


def _python_env_variables() -> set[str]:
    variables: set[str] = set()
    for scan_path in PYTHON_SCAN_PATHS:
        for path in _iter_files(scan_path, (".py",)):
            text = _read(path)
            variables.update(PYTHON_ENV_PATTERN.findall(text))
            variables.update(PYTHON_ENV_ASSIGN_PATTERN.findall(text))
    return variables


def _shell_env_variables() -> set[str]:
    variables: set[str] = set()
    for scan_path in SHELL_SCAN_PATHS:
        for path in _iter_files(scan_path, (".sh",)):
            variables.update(SHELL_ENV_DEFAULT_PATTERN.findall(_read(path)))
    return variables


def _compose_env_variables() -> set[str]:
    variables: set[str] = set()
    for path in COMPOSE_SCAN_PATHS:
        variables.update(COMPOSE_ENV_PATTERN.findall(_read(path)))
    return variables


def _dockerfile_env_variables() -> set[str]:
    variables: set[str] = set()
    for path in DOCKERFILE_PATHS:
        variables.update(DOCKER_ENV_PATTERN.findall(_read(path)))
    return variables


@pytest.mark.fast
def test_environment_contract_covers_consumed_variables():
    consumed_variables = (
        _python_env_variables()
        | _shell_env_variables()
        | _compose_env_variables()
        | _dockerfile_env_variables()
    )

    missing = consumed_variables - _contract_variables()

    assert missing == set()
