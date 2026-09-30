"""Startup-only index for organization-owned authoritative policies."""

from pymongo import ASCENDING
from pymongo.errors import PyMongoError


def initialize_policy_index(db) -> None:
    """Scope legacy lookups and enforce uniqueness for newly generated rows."""
    try:
        db.policies.create_index(
            [("organization_id", ASCENDING), ("context_id", ASCENDING)],
            name="organization_context_lookup",
        )
        db.policies.create_index(
            [("organization_id", ASCENDING), ("context_id", ASCENDING)],
            name="organization_context_generated_unique",
            unique=True,
            partialFilterExpression={"generation_guard": True},
        )
    except PyMongoError:
        raise RuntimeError("Policy persistence index initialization failed.") from None
