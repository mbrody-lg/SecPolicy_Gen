"""Security contract for the disposable local OIDC provider fixture."""

import json
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
REALM_PATH = ROOT_DIR / "infrastructure" / "keycloak" / "secpolicygen-realm.json"
COMPOSE_BASE_PATH = ROOT_DIR / "infrastructure" / "docker-compose.yml"
COMPOSE_LOCAL_PATH = ROOT_DIR / "infrastructure" / "docker-compose.local-oidc.yml"


@pytest.mark.fast
def test_local_oidc_client_uses_code_flow_pkce_and_exact_redirects():
    realm = json.loads(REALM_PATH.read_text(encoding="utf-8"))
    client = realm["clients"][0]

    assert client["standardFlowEnabled"] is True
    assert client["directAccessGrantsEnabled"] is False
    assert client["publicClient"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["redirectUris"]
    assert all("*" not in uri for uri in client["redirectUris"])
    assert all("*" not in origin for origin in client["webOrigins"])


@pytest.mark.fast
def test_local_tls_private_material_is_not_tracked():
    gitignore = (ROOT_DIR / ".gitignore").read_text(encoding="utf-8")
    key_paths = (ROOT_DIR / "infrastructure").rglob("*.key")

    assert "/infrastructure/.local-certs/" in gitignore
    assert all(".local-certs" in path.parts for path in key_paths)


@pytest.mark.fast
def test_local_provider_is_optional_and_ca_private_key_is_never_mounted():
    base_compose = COMPOSE_BASE_PATH.read_text(encoding="utf-8")
    local_compose = COMPOSE_LOCAL_PATH.read_text(encoding="utf-8")

    assert "identity:" not in base_compose
    assert ".local-certs" not in base_compose
    assert "identity:" in local_compose
    assert "LOCAL_OIDC_CERT_UID" in local_compose
    assert "ca.key" not in local_compose
    assert "./.local-certs:/" not in local_compose
