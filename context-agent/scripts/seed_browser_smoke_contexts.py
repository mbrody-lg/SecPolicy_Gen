"""Seed deterministic Context Detail records for Docker browser smoke tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bson import ObjectId

ROOT_PATH = Path(__file__).resolve().parents[1]
TESTS_PATH = ROOT_PATH / "tests"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(TESTS_PATH) not in sys.path:
    sys.path.insert(0, str(TESTS_PATH))

from app import create_app, mongo  # noqa: E402
from app.access_control import (  # noqa: E402
    provision_membership,
    provision_organization,
    sync_principal,
)
from ui_workflow_fixtures import context_document, interactions  # noqa: E402


STATES = (
    "questions",
    "task_needs_context",
    "executed",
    "final_needs_improvement",
    "ready",
)
SMOKE_SUBJECT = "browser-smoke-user"
SMOKE_ORGANIZATION_ID = "browser-smoke"


def _session_cookie(app) -> dict[str, str]:
    principal = {
        "issuer": app.config["OIDC_ISSUER_URL"],
        "subject": SMOKE_SUBJECT,
    }
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["principal"] = principal
        cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    if cookie is None:
        raise RuntimeError("Browser smoke session cookie was not created.")
    return {"name": cookie.key, "value": cookie.value}


def main() -> None:
    app = create_app()
    urls = {}
    with app.app_context():
        principal = sync_principal(
            issuer=app.config["OIDC_ISSUER_URL"],
            subject=SMOKE_SUBJECT,
        )
        organization = provision_organization(
            organization_id=SMOKE_ORGANIZATION_ID,
            name="Browser Smoke Organization",
        )
        provision_membership(
            principal_id=principal["_id"],
            organization_id=organization["organization_id"],
            roles=("admin",),
            is_default=True,
        )
        mongo.db.contexts.delete_many({"browser_smoke": True})
        mongo.db.interactions.delete_many({"browser_smoke": True})

        for state in STATES:
            context_id = str(ObjectId())
            context = context_document(context_id, state)
            context["browser_smoke"] = True
            context["organization_id"] = SMOKE_ORGANIZATION_ID
            mongo.db.contexts.insert_one(context)

            seeded_interactions = []
            for interaction in interactions(context_id):
                interaction["browser_smoke"] = True
                interaction["organization_id"] = SMOKE_ORGANIZATION_ID
                seeded_interactions.append(interaction)
            mongo.db.interactions.insert_many(seeded_interactions)
            urls[state] = f"/context/{context_id}"

    print(json.dumps({"contexts": urls, "session": _session_cookie(app)}, sort_keys=True))


if __name__ == "__main__":
    main()
