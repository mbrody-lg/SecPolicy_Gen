import json

from app import mongo
from app.services import logic


SENTINEL_SECRET = "sentinel-secret-value-do-not-leak"


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
