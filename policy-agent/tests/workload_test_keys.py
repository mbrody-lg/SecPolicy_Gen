"""Public, deterministic Ed25519 fixtures; never use these keys in deployment."""

import base64
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SEEDS = {
    "context-agent": bytes([1]) * 32,
    "validator-agent": bytes([2]) * 32,
    "docker-agent": bytes([3]) * 32,
}
KEY_IDS = {
    "context-agent": "context-test-v1",
    "validator-agent": "validator-test-v1",
    "docker-agent": "candidate-test-v1",
}
TEST_TENANTS = [
    "tenant-a", "test-organization", "functional-smoke-org",
    "another-organization", "organization-a",
]


def signing_key(subject):
    return Ed25519PrivateKey.from_private_bytes(SEEDS[subject])


def verifier_registry(subject):
    public_key = signing_key(subject).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    tenants = ["tenant-a"] if subject == "docker-agent" else TEST_TENANTS
    return json.dumps({KEY_IDS[subject]: {
        "public_key_b64": base64.b64encode(public_key).decode("ascii"),
        "tenant_ids": tenants,
    }})


def configure_test_workload_env():
    os.environ.setdefault("WORKLOAD_CONTEXT_SIGNING_KID", KEY_IDS["context-agent"])
    os.environ.setdefault(
        "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(SEEDS["context-agent"]).decode("ascii"),
    )
    os.environ.setdefault("WORKLOAD_VALIDATOR_SIGNING_KID", KEY_IDS["validator-agent"])
    os.environ.setdefault(
        "WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(SEEDS["validator-agent"]).decode("ascii"),
    )
    for subject, name in (
        ("context-agent", "WORKLOAD_CONTEXT_VERIFY_KEYS"),
        ("validator-agent", "WORKLOAD_VALIDATOR_VERIFY_KEYS"),
        ("docker-agent", "WORKLOAD_CANDIDATE_VERIFY_KEYS"),
    ):
        os.environ.setdefault(name, verifier_registry(subject))


def configure_ephemeral_workload_env(monkeypatch):
    """Use fresh in-memory keys for non-test-mode app configuration checks."""
    keys = {
        subject: Ed25519PrivateKey.generate()
        for subject in ("context-agent", "validator-agent", "docker-agent")
    }
    for subject, signing_prefix in (
        ("context-agent", "WORKLOAD_CONTEXT"),
        ("validator-agent", "WORKLOAD_VALIDATOR"),
    ):
        monkeypatch.setenv(f"{signing_prefix}_SIGNING_KID", KEY_IDS[subject])
        monkeypatch.setenv(
            f"{signing_prefix}_SIGNING_PRIVATE_KEY_B64",
            base64.b64encode(keys[subject].private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )).decode("ascii"),
        )
    for subject, name in (
        ("context-agent", "WORKLOAD_CONTEXT_VERIFY_KEYS"),
        ("validator-agent", "WORKLOAD_VALIDATOR_VERIFY_KEYS"),
        ("docker-agent", "WORKLOAD_CANDIDATE_VERIFY_KEYS"),
    ):
        public_key = keys[subject].public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        monkeypatch.setenv(name, json.dumps({KEY_IDS[subject]: {
            "public_key_b64": base64.b64encode(public_key).decode("ascii"),
            "tenant_ids": ["tenant-a"],
        }}))
