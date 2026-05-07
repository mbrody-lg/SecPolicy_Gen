import json

from app import mongo
from app.services import logic


SENTINEL_SECRET = "sentinel-secret-value-do-not-leak"


def test_readiness_payload_does_not_include_secret_values(app, monkeypatch):
    class FailingAdmin:
        @staticmethod
        def command(name):
            assert name == "ping"
            raise RuntimeError(SENTINEL_SECRET)

    class FailingMongoClient:
        admin = FailingAdmin()

    monkeypatch.setattr(
        logic,
        "load_policy_config",
        lambda: {
            "type": "openai",
            "name": "OpenAI-Policy",
            "model": "gpt-4o-mini",
            "roles": [
                {
                    "vector": [
                        {
                            "chroma": {
                                "collection": ["legal_norms"],
                            }
                        }
                    ]
                }
            ],
        },
    )
    app.config["SECRET_KEY"] = SENTINEL_SECRET
    app.config["MONGO_URI"] = f"mongodb://user:{SENTINEL_SECRET}@mongo:27017/policydb"
    monkeypatch.setattr(mongo, "cx", FailingMongoClient())
    monkeypatch.setenv("CHROMA_HOST", SENTINEL_SECRET)
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_READINESS_MODE", "config_only")

    with app.app_context():
        payload, status_code = logic.get_readiness_status()

    assert status_code == 503
    assert SENTINEL_SECRET not in json.dumps(payload, sort_keys=True)
