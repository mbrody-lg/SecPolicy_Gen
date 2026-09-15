import importlib.util
from pathlib import Path

import mongomock

from app import mongo


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_tenant_scope.py"
SPEC = importlib.util.spec_from_file_location("migrate_tenant_scope", SCRIPT)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_migration_is_dry_run_by_default(app, monkeypatch):
    fake_db = mongomock.MongoClient().db
    monkeypatch.setattr(mongo, "db", fake_db, raising=False)
    fake_db.organizations.insert_one({"organization_id": "organization-a", "status": "active"})
    fake_db.contexts.insert_one({"name": "legacy"})

    with app.app_context():
        report = migration.migrate_legacy_records(organization_id="organization-a")

    assert report["mode"] == "dry-run"
    assert report["unowned_records"]["contexts"] == 1
    assert "organization_id" not in mongo.db.contexts.find_one({"name": "legacy"})


def test_migration_assigns_unowned_records_only_when_applied(app, monkeypatch):
    fake_db = mongomock.MongoClient().db
    monkeypatch.setattr(mongo, "db", fake_db, raising=False)
    fake_db.organizations.insert_one({"organization_id": "organization-a", "status": "active"})
    fake_db.contexts.insert_one({"name": "legacy"})
    fake_db.contexts.insert_one({"name": "owned", "organization_id": "organization-b"})

    with app.app_context():
        report = migration.migrate_legacy_records(
            organization_id="organization-a",
            apply=True,
        )

    assert report["mode"] == "apply"
    assert mongo.db.contexts.find_one({"name": "legacy"})["organization_id"] == "organization-a"
    assert mongo.db.contexts.find_one({"name": "owned"})["organization_id"] == "organization-b"
