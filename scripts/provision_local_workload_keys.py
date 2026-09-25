"""Provision fresh local workload keys into ignored env files, never stdout."""

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / "infrastructure" / ".env"
EXAMPLE_ENV = ROOT / "infrastructure" / ".env.example"
CANDIDATE_ENV = ROOT / "infrastructure" / ".env.candidate.local"


def _key_pair():
    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(seed).decode(), base64.b64encode(public).decode()


def provision(env_path: Path, candidate_path: Path, tenant_id: str):
    if not tenant_id or len(tenant_id) > 64 or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        for char in tenant_id
    ):
        raise ValueError("tenant_id must be a 1-64 character workload tenant ID")
    if env_path.resolve() == candidate_path.resolve() or env_path.is_symlink() or candidate_path.is_symlink():
        raise ValueError("workload env destinations must be distinct regular paths")
    source = env_path.read_text() if env_path.exists() else EXAMPLE_ENV.read_text()
    values = {}
    candidate_values = {}
    for name in ("context", "validator", "candidate"):
        seed, public = _key_pair()
        kid = f"{name}-local-v1"
        registry = json.dumps({kid: {"public_key_b64": public, "tenant_ids": [tenant_id]}}, separators=(",", ":"))
        values[f"WORKLOAD_{name.upper()}_VERIFY_KEYS"] = registry
        if name == "candidate":
            candidate_values = {
                "WORKLOAD_CANDIDATE_SIGNING_KID": kid,
                "WORKLOAD_CANDIDATE_SIGNING_PRIVATE_KEY_B64": seed,
            }
        else:
            values[f"WORKLOAD_{name.upper()}_SIGNING_KID"] = kid
            values[f"WORKLOAD_{name.upper()}_SIGNING_PRIVATE_KEY_B64"] = seed
    lines = []
    replaced = set()
    for line in source.splitlines():
        key = line.split("=", 1)[0]
        if key in values:
            lines.append(f"{key}={values[key]}")
            replaced.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in replaced)
    pending = []
    try:
        for path, content in (
            (env_path, "\n".join(lines) + "\n"),
            (candidate_path, "\n".join(f"{key}={value}" for key, value in candidate_values.items()) + "\n"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.tmp.", suffix=".local", dir=path.parent)
            pending.append((path, Path(temporary)))
            with os.fdopen(fd, "w") as stream:
                stream.write(content)
            os.chmod(temporary, 0o600)
        for path, temporary in pending:
            if path.is_symlink():
                raise ValueError("workload env destinations cannot be symlinks")
            os.replace(temporary, path)
    finally:
        for _, temporary in pending:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="Local tenant allowed by the generated keys")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--candidate-env-file", type=Path, default=CANDIDATE_ENV)
    args = parser.parse_args()
    provision(args.env_file, args.candidate_env_file, args.tenant_id)
    print("Fresh local workload keys provisioned in ignored env files.")
