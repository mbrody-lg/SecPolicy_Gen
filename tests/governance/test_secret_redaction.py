"""Repository-level checks for shared diagnostic redaction tooling."""

import subprocess
from pathlib import Path


SENTINEL_SECRET = "sentinel-secret-value-do-not-leak"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_diagnostic_redaction_script_masks_known_secret_values():
    command = f"source {REPO_ROOT / 'scripts' / 'redaction.sh'}; redact_sensitive_output"
    result = subprocess.run(
        ["bash", "-lc", command],
        input=(
            f"OPENAI_API_KEY={SENTINEL_SECRET}\n"
            f"mongo password {SENTINEL_SECRET}\n"
        ),
        text=True,
        capture_output=True,
        check=True,
        env={
            "OPENAI_API_KEY": SENTINEL_SECRET,
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
    )

    assert SENTINEL_SECRET not in result.stdout
    assert "[REDACTED:OPENAI_API_KEY]" in result.stdout
