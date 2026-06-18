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
from ui_workflow_fixtures import context_document, interactions  # noqa: E402


STATES = (
    "questions",
    "task_needs_context",
    "executed",
    "final_needs_improvement",
    "ready",
)


def main() -> None:
    app = create_app()
    urls = {}
    with app.app_context():
        mongo.db.contexts.delete_many({"browser_smoke": True})
        mongo.db.interactions.delete_many({"browser_smoke": True})

        for state in STATES:
            context_id = str(ObjectId())
            context = context_document(context_id, state)
            context["browser_smoke"] = True
            mongo.db.contexts.insert_one(context)

            seeded_interactions = []
            for interaction in interactions(context_id):
                interaction["browser_smoke"] = True
                seeded_interactions.append(interaction)
            mongo.db.interactions.insert_many(seeded_interactions)
            urls[state] = f"/context/{context_id}"

    print(json.dumps({"contexts": urls}, sort_keys=True))


if __name__ == "__main__":
    main()
