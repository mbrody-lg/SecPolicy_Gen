"""Audit or assign legacy Context Agent records to one explicit organization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from app import create_app, mongo  # noqa: E402
from app.tenant_scope import ensure_tenant_indexes  # noqa: E402


OWNED_COLLECTIONS = (
    "contexts",
    "interactions",
    "pipeline_jobs",
    "pipeline_events",
    "pipeline_diagnostics",
)
MISSING_OWNER = {
    "$or": [
        {"organization_id": {"$exists": False}},
        {"organization_id": None},
        {"organization_id": ""},
    ]
}


def migrate_legacy_records(*, organization_id: str, apply: bool = False) -> dict:
    """Return counts and optionally assign every unowned legacy record."""
    organization = mongo.db.organizations.find_one(
        {"organization_id": organization_id, "status": "active"}
    )
    if not organization:
        raise ValueError("Target organization must exist and be active.")

    counts = {
        name: getattr(mongo.db, name).count_documents(MISSING_OWNER)
        for name in OWNED_COLLECTIONS
    }
    if apply:
        for name in OWNED_COLLECTIONS:
            getattr(mongo.db, name).update_many(
                MISSING_OWNER,
                {"$set": {"organization_id": organization_id}},
            )
        ensure_tenant_indexes()
    return {
        "mode": "apply" if apply else "dry-run",
        "organization_id": organization_id,
        "unowned_records": counts,
        "total": sum(counts.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("organization_id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print(json.dumps(migrate_legacy_records(
            organization_id=args.organization_id,
            apply=args.apply,
        ), sort_keys=True))


if __name__ == "__main__":
    main()
