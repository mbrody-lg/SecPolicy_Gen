"""Tenant-bound, one-use Ed25519 credentials for internal agent requests."""

from __future__ import annotations

import base64
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from pymongo.errors import DuplicateKeyError, PyMongoError


TOKEN_LIFETIME_SECONDS = 60
MAX_CLOCK_SKEW_SECONDS = 5
MAX_ROTATION_OVERLAP_SECONDS = 600
TOKEN_TYPE = "secpolicy-workload-v1"
TENANT_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24,64}$")


class InvalidWorkloadToken(Exception):
    pass


class ForbiddenWorkloadToken(Exception):
    pass


class WorkloadReplay(Exception):
    pass


class WorkloadReplayStoreUnavailable(Exception):
    pass


@dataclass(frozen=True)
class VerifierKey:
    subject: str
    public_key: Ed25519PublicKey
    tenant_ids: frozenset[str]
    accept_until: int | None


def _decode_key(name: str, value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a base64-encoded Ed25519 key.") from exc
    if len(raw) != 32:
        raise ValueError(f"{name} must be a base64-encoded Ed25519 key.")
    return raw


_TEST_SEEDS = frozenset(bytes([value]) * 32 for value in (1, 2, 3))
_TEST_PUBLIC_KEYS = frozenset(
    Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ) for seed in _TEST_SEEDS
)


def load_signing_key(name: str, value: str, *, testing: bool = False) -> Ed25519PrivateKey:
    """Load the caller-only raw private seed; never pass it to a verifier."""
    raw = _decode_key(name, value)
    if not testing and raw in _TEST_SEEDS:
        raise ValueError(f"{name} uses a public test-only signing key.")
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_verifier_keys(
    name: str, value: str, *, subject: str, single_tenant: bool = False,
    testing: bool = False,
) -> dict[str, VerifierKey]:
    """Load one current public key and at most one time-bounded previous key."""
    try:
        entries = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a JSON verification-key registry.") from exc
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 2:
        raise ValueError(f"{name} must contain one or two verification keys.")
    now = int(time.time())
    result = {}
    current_count = 0
    for kid, entry in entries.items():
        if not isinstance(kid, str) or not KEY_ID_PATTERN.fullmatch(kid):
            raise ValueError(f"{name} contains an invalid key id.")
        if not isinstance(entry, dict) or set(entry) not in (
            {"public_key_b64", "tenant_ids"},
            {"public_key_b64", "tenant_ids", "accept_until"},
        ):
            raise ValueError(f"{name} contains an invalid key record.")
        tenant_ids = entry["tenant_ids"]
        if (
            not isinstance(tenant_ids, list)
            or not tenant_ids
            or any(not isinstance(item, str) or not TENANT_PATTERN.fullmatch(item) for item in tenant_ids)
            or len(tenant_ids) != len(set(tenant_ids))
            or (single_tenant and len(tenant_ids) != 1)
        ):
            raise ValueError(f"{name} must bind each key to explicit tenant IDs.")
        accept_until = entry.get("accept_until")
        if accept_until is None:
            current_count += 1
        elif (
            type(accept_until) is not int
            or accept_until > now + MAX_ROTATION_OVERLAP_SECONDS
        ):
            raise ValueError(f"{name} previous-key window must be at most 600 seconds.")
        raw_public_key = _decode_key(name, entry["public_key_b64"])
        if not testing and raw_public_key in _TEST_PUBLIC_KEYS:
            raise ValueError(f"{name} uses a public test-only verification key.")
        result[kid] = VerifierKey(
            subject=subject,
            public_key=Ed25519PublicKey.from_public_bytes(raw_public_key),
            tenant_ids=frozenset(tenant_ids),
            accept_until=accept_until,
        )
    if current_count != 1:
        raise ValueError(f"{name} must have exactly one current verification key.")
    return result


def combine_verifier_keys(*registries: dict[str, VerifierKey]) -> dict[str, VerifierKey]:
    combined = {}
    public_keys = set()
    for registry in registries:
        if set(combined).intersection(registry):
            raise ValueError("Workload key IDs must be unique across callers.")
        for verifier in registry.values():
            public_bytes = verifier.public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            if public_bytes in public_keys:
                raise ValueError("Workload public keys must be distinct across callers.")
            public_keys.add(public_bytes)
        combined.update(registry)
    return combined


def mint_token(
    *, key: Ed25519PrivateKey, kid: str, subject: str, audience: str,
    scope: str, tenant_id: str, path: str,
) -> str:
    """Mint a scoped request from an already verified tenant context."""
    if not isinstance(tenant_id, str) or not TENANT_PATTERN.fullmatch(tenant_id):
        raise ValueError("A verified tenant is required for workload authentication.")
    if not isinstance(kid, str) or not KEY_ID_PATTERN.fullmatch(kid):
        raise ValueError("A configured workload key ID is required.")
    if not path.startswith("/") or "?" in path or not scope:
        raise ValueError("A fixed workload route and scope are required.")
    issued_at = int(time.time())
    return jwt.encode({
        "version": 1,
        "sub": subject,
        "aud": audience,
        "scopes": [scope],
        "tenant_id": tenant_id,
        "method": "POST",
        "path": path,
        "iat": issued_at,
        "exp": issued_at + TOKEN_LIFETIME_SECONDS,
        "jti": secrets.token_urlsafe(24),
    }, key, algorithm="EdDSA", headers={"kid": kid, "typ": TOKEN_TYPE})


def verify_token(
    credential: str,
    *,
    caller_keys: dict[str, VerifierKey],
    allowed_scopes: dict[str, frozenset[str]],
    audience: str,
    scope: str,
    method: str,
    path: str,
) -> dict:
    """Verify the allowlisted key and claims before replay or domain work."""
    if not isinstance(credential, str) or not credential or len(credential) > 4096:
        raise InvalidWorkloadToken
    try:
        header = jwt.get_unverified_header(credential)
        if (
            set(header) != {"alg", "kid", "typ"}
            or header["alg"] != "EdDSA"
            or header["typ"] != TOKEN_TYPE
            or not isinstance(header["kid"], str)
        ):
            raise InvalidWorkloadToken
        verifier = caller_keys.get(header["kid"])
        if verifier is None:
            raise InvalidWorkloadToken
        claims = jwt.decode(
            credential, verifier.public_key, algorithms=["EdDSA"],
            options={"verify_exp": False, "verify_iat": False, "verify_aud": False},
        )
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise InvalidWorkloadToken from exc
    if not isinstance(claims, dict) or claims.get("sub") != verifier.subject:
        raise InvalidWorkloadToken
    now = int(time.time())
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    scopes = claims.get("scopes")
    if (
        type(claims.get("version")) is not int
        or claims["version"] != 1
        or type(issued_at) is not int
        or type(expires_at) is not int
        or issued_at > now + MAX_CLOCK_SKEW_SECONDS
        or issued_at < now - TOKEN_LIFETIME_SECONDS
        or expires_at <= now
        or expires_at - issued_at != TOKEN_LIFETIME_SECONDS
        or (verifier.accept_until is not None and now > verifier.accept_until)
        or not isinstance(claims.get("jti"), str)
        or not NONCE_PATTERN.fullmatch(claims["jti"])
        or not isinstance(claims.get("tenant_id"), str)
        or not TENANT_PATTERN.fullmatch(claims["tenant_id"])
        or claims.get("method") != method
        or claims.get("path") != path
        or not isinstance(scopes, list)
        or not scopes
        or any(not isinstance(item, str) for item in scopes)
    ):
        raise InvalidWorkloadToken
    if claims["tenant_id"] not in verifier.tenant_ids:
        raise ForbiddenWorkloadToken
    if claims.get("aud") != audience or scope not in scopes:
        raise ForbiddenWorkloadToken
    if not set(scopes).issubset(allowed_scopes.get(verifier.subject, frozenset())):
        raise ForbiddenWorkloadToken
    return claims


def initialize_replay_store(db) -> None:
    """Create the expiry index before the service accepts protected traffic."""
    try:
        db.workload_nonces.create_index("expires_at", expireAfterSeconds=0)
    except PyMongoError as exc:
        raise WorkloadReplayStoreUnavailable from exc


def consume_token(db, credential: str, claims: dict) -> None:
    """Atomically reject replay across processes using the initialized store."""
    nonce_id = sha256(credential.encode("utf-8")).hexdigest()
    try:
        db.workload_nonces.insert_one({
            "_id": nonce_id,
            "expires_at": datetime.fromtimestamp(claims["exp"], timezone.utc),
        })
    except DuplicateKeyError as exc:
        raise WorkloadReplay from exc
    except PyMongoError as exc:
        raise WorkloadReplayStoreUnavailable from exc
