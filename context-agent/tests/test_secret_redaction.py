import json
import subprocess
from pathlib import Path

from app import mongo
from app.services import logic


SENTINEL_SECRET = "sentinel-secret-value-do-not-leak"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _assert_secret_absent(payload):
    assert SENTINEL_SECRET not in json.dumps(payload, sort_keys=True)


def test_readiness_payload_does_not_include_secret_values(app, monkeypatch):
    class FailingAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            raise RuntimeError(SENTINEL_SECRET)

    class FailingMongoClient:
        admin = FailingAdmin()

    app.config["SECRET_KEY"] = SENTINEL_SECRET
    app.config["MONGO_URI"] = f"mongodb://user:{SENTINEL_SECRET}@mongo:27017/contextdb"
    monkeypatch.setattr(mongo, "cx", FailingMongoClient())

    with app.app_context():
        payload = logic.get_readiness_status()

    assert payload["status"] == "not_ready"
    _assert_secret_absent(payload)


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
