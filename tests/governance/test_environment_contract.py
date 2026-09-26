"""Static coverage checks for the repository environment contract."""

import base64
import json
import re
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT_DIR / "docs" / "playbooks" / "environment-configuration.md"
ENV_EXAMPLE_PATH = ROOT_DIR / "infrastructure" / ".env.example"
SMOKE_ENV_EXAMPLE_PATH = ROOT_DIR / "infrastructure" / ".env.smoke.example"
FUNCTIONAL_SMOKE_PATH = ROOT_DIR / "scripts" / "run_docker_functional_smoke.sh"
GITIGNORE_PATH = ROOT_DIR / ".gitignore"
SERVICE_ENV_EXAMPLE_PATHS = [
    ROOT_DIR / "context-agent" / ".env.example",
    ROOT_DIR / "policy-agent" / ".env.example",
    ROOT_DIR / "validator-agent" / ".env.example",
]

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
REQUIRED_ENV_EXAMPLE_VARIABLES = {
    "CHROMA_HOST",
    "CHROMA_PORT",
    "CHROMA_READINESS_MODE",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_ISSUER_URL",
    "OIDC_REDIRECT_URI",
    "OIDC_SCOPES",
    "DEBUG",
    "FLASK_ENV",
    "FLASK_RUN_DEBUG",
    "FLASK_SECRET_KEY",
    "MAX_CONTENT_LENGTH",
    "MISTRAL_API_KEY",
    "MISTRAL_API_URL",
    "MONGO_URI",
    "OPENAI_API_KEY",
    "OPENAI_API_URL",
    "POLICY_AGENT_ALLOW_MODEL_DOWNLOAD",
    "POLICY_CALLBACK_TOKEN",
    "POLICY_AGENT_TIMEOUT_SECONDS",
    "POLICY_AGENT_URL",
    "PIPELINE_JOB_STALE_AFTER_SECONDS",
    "RAG_VALIDATE_CHROMA",
    "WORKLOAD_CONTEXT_SIGNING_KID",
    "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64",
    "WORKLOAD_CONTEXT_VERIFY_KEYS",
    "WORKLOAD_VALIDATOR_SIGNING_KID",
    "WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64",
    "WORKLOAD_VALIDATOR_VERIFY_KEYS",
    "WORKLOAD_CANDIDATE_VERIFY_KEYS",
    "SESSION_COOKIE_SECURE",
    "TESTING",
    "TRUSTED_HOSTS",
    "VALIDATOR_AGENT_TIMEOUT_SECONDS",
    "VALIDATOR_AGENT_URL",
}
EXTERNAL_AGENT_CONFIG_VARIABLES = {
    "AGENT_CONFIG_DIR",
    "CONTEXT_AGENT_CONFIG_PATH",
    "CONTEXT_QUESTIONS_CONFIG_PATH",
    "POLICY_AGENT_CONFIG_PATH",
    "VALIDATOR_AGENT_CONFIG_PATH",
}
SECRET_EXAMPLE_VARIABLES = {
    "OIDC_CLIENT_SECRET",
    "FLASK_SECRET_KEY",
    "MISTRAL_API_KEY",
    "OPENAI_API_KEY",
    "POLICY_CALLBACK_TOKEN",
    "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64",
    "WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64",
}
SIGNING_SEEDS = {
    "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64",
    "WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64",
}
VERIFIER_REGISTRIES = {
    "WORKLOAD_CONTEXT_VERIFY_KEYS",
    "WORKLOAD_VALIDATOR_VERIFY_KEYS",
    "WORKLOAD_CANDIDATE_VERIFY_KEYS",
}
LIVE_SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj|or-v1)-", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]+\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


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


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read(ENV_EXAMPLE_PATH).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key] = value
    return values


def _env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key] = value
    return values


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


@pytest.mark.fast
def test_environment_contract_covers_external_agent_configuration():
    missing = EXTERNAL_AGENT_CONFIG_VARIABLES - _contract_variables()

    assert missing == set()


@pytest.mark.fast
def test_env_example_covers_contract_surface_with_fake_secrets():
    env_values = _env_example_values()

    missing = REQUIRED_ENV_EXAMPLE_VARIABLES - set(env_values)
    undocumented = set(env_values) - _contract_variables()
    unsafe_secret_examples = {
        key: env_values[key]
        for key in SECRET_EXAMPLE_VARIABLES
        if key in env_values and key not in SIGNING_SEEDS
        and not env_values[key].startswith("fake-local-")
    }
    live_like_values = {
        key: value
        for key, value in env_values.items()
        if any(pattern.search(value) for pattern in LIVE_SECRET_PATTERNS)
    }

    assert missing == set()
    assert undocumented == set()
    assert unsafe_secret_examples == {}
    assert live_like_values == {}


@pytest.mark.fast
def test_smoke_env_example_is_complete_and_fake_only():
    env_values = _env_file_values(SMOKE_ENV_EXAMPLE_PATH)

    missing = REQUIRED_ENV_EXAMPLE_VARIABLES - set(env_values)
    undocumented = set(env_values) - _contract_variables()
    unsafe_secret_examples = {
        key: env_values[key]
        for key in SECRET_EXAMPLE_VARIABLES
        if key in env_values and key not in SIGNING_SEEDS
        and not env_values[key].startswith("fake-local-")
    }
    live_like_values = {
        key: value
        for key, value in env_values.items()
        if any(pattern.search(value) for pattern in LIVE_SECRET_PATTERNS)
    }

    assert missing == set()
    assert undocumented == set()
    assert unsafe_secret_examples == {}
    assert live_like_values == {}


@pytest.mark.fast
def test_functional_smoke_env_is_separate_from_developer_env():
    script = _read(FUNCTIONAL_SMOKE_PATH)
    gitignore = _read(GITIGNORE_PATH).splitlines()

    assert 'LOCAL_ENV_FILE="${INFRA_DIR}/.env"' in script
    assert 'SMOKE_ENV_FILE="${INFRA_DIR}/.env.smoke"' in script
    assert 'SMOKE_ENV_FILE="$SMOKE_ENV_OVERRIDE"' in script
    assert 'SMOKE_ENV_EXAMPLE_FILE="${INFRA_DIR}/.env.smoke.example"' in script
    assert 'TMP_ENV_FILE="$LOCAL_ENV_FILE"' in script
    assert 'cp "$SMOKE_ENV_EXAMPLE_FILE" "$TMP_ENV_FILE"' in script
    assert 'cp "$INFRA_DIR/.env.example" "$TMP_ENV_FILE"' not in script
    assert "/infrastructure/.env.smoke" in gitignore


@pytest.mark.fast
def test_service_env_examples_use_fake_local_secret_values():
    unsafe_secret_examples: dict[str, str] = {}
    live_like_values: dict[str, str] = {}
    undocumented: set[str] = set()

    for path in SERVICE_ENV_EXAMPLE_PATHS:
        env_values = _env_file_values(path)
        undocumented.update(set(env_values) - _contract_variables())
        unsafe_secret_examples.update(
            {
                f"{path.name}:{key}": env_values[key]
                for key in SECRET_EXAMPLE_VARIABLES
                if key in env_values and key not in SIGNING_SEEDS
                and not env_values[key].startswith("fake-local-")
            }
        )
        live_like_values.update(
            {
                f"{path.name}:{key}": value
                for key, value in env_values.items()
                if any(pattern.search(value) for pattern in LIVE_SECRET_PATTERNS)
            }
        )

    assert undocumented == set()
    assert unsafe_secret_examples == {}
    assert live_like_values == {}


@pytest.mark.fast
def test_workload_examples_separate_signers_from_verifiers():
    context = _env_file_values(SERVICE_ENV_EXAMPLE_PATHS[0])
    policy = _env_file_values(SERVICE_ENV_EXAMPLE_PATHS[1])
    validator = _env_file_values(SERVICE_ENV_EXAMPLE_PATHS[2])
    expected = {
        "context": {"WORKLOAD_CONTEXT_SIGNING_KID", "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64"},
        "policy": VERIFIER_REGISTRIES,
        "validator": {"WORKLOAD_CONTEXT_VERIFY_KEYS", "WORKLOAD_CANDIDATE_VERIFY_KEYS",
                      "WORKLOAD_VALIDATOR_SIGNING_KID", "WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64"},
    }
    for name, values in (("context", context), ("policy", policy), ("validator", validator)):
        assert {key for key in values if key.startswith("WORKLOAD_")} == expected[name]
        assert "SERVICE_AUTH_TOKEN" not in values

    for path in (ENV_EXAMPLE_PATH, SMOKE_ENV_EXAMPLE_PATH):
        values = _env_file_values(path)
        assert {key for key in values if key.startswith("WORKLOAD_")} == (
            SIGNING_SEEDS | VERIFIER_REGISTRIES
            | {"WORKLOAD_CONTEXT_SIGNING_KID", "WORKLOAD_VALIDATOR_SIGNING_KID"}
        )
        assert "test" in _read(path).lower()
        for key in SIGNING_SEEDS:
            assert len(base64.b64decode(values[key], validate=True)) == 32
        for key in VERIFIER_REGISTRIES:
            registry = json.loads(values[key])
            assert len(registry) == 1
            assert all(set(record) == {"public_key_b64", "tenant_ids"}
                       and record["tenant_ids"] for record in registry.values())
        assert len(json.loads(values["WORKLOAD_CANDIDATE_VERIFY_KEYS"])["candidate-test-v1"]["tenant_ids"]) == 1
