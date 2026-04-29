"""Source manifest loading and validation for policy-agent RAG."""

import re
from pathlib import Path
from typing import Any

import yaml


DEFAULT_RAG_SOURCES_PATH = Path("app/config/rag_sources.yaml")
REQUIRED_SOURCE_FIELDS = {"id", "path", "collection", "family", "metadata"}
REQUIRED_METADATA_FIELDS = {
    "source_kind",
    "jurisdiction",
    "language",
    "applicability",
    "priority",
}
CHROMA_COLLECTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,61}[A-Za-z0-9]$")


class RagSourceManifestError(ValueError):
    """Raised when the RAG source manifest is invalid."""


def load_rag_source_manifest(path: str | Path = DEFAULT_RAG_SOURCES_PATH) -> dict[str, Any]:
    """Load and validate the RAG source manifest."""
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as manifest_file:
        manifest = yaml.safe_load(manifest_file)
    validate_rag_source_manifest(manifest)
    return manifest


def validate_rag_source_manifest(manifest: dict[str, Any] | None) -> None:
    """Validate the minimum manifest shape required for source governance."""
    if not isinstance(manifest, dict):
        raise RagSourceManifestError("RAG source manifest must be a mapping.")

    if manifest.get("version") != 1:
        raise RagSourceManifestError("RAG source manifest version must be 1.")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RagSourceManifestError("RAG source manifest must define at least one source.")

    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        _validate_source(source, index, source_ids)


def get_manifest_collections(manifest: dict[str, Any]) -> list[str]:
    """Return unique collection names in manifest order."""
    collections: list[str] = []
    for source in manifest.get("sources", []):
        collection = source.get("collection")
        if collection not in collections:
            collections.append(collection)
    return collections


def get_sources_by_family(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Group source entries by collection family."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in manifest.get("sources", []):
        grouped.setdefault(source["family"], []).append(source)
    return grouped


def _validate_source(source: Any, index: int, source_ids: set[str]) -> None:
    if not isinstance(source, dict):
        raise RagSourceManifestError(f"RAG source at index {index} must be a mapping.")

    missing = sorted(REQUIRED_SOURCE_FIELDS - set(source))
    if missing:
        raise RagSourceManifestError(
            f"RAG source at index {index} is missing required fields: {', '.join(missing)}."
        )

    source_id = source["id"]
    if not isinstance(source_id, str) or not source_id.strip():
        raise RagSourceManifestError(f"RAG source at index {index} has an invalid id.")
    if source_id in source_ids:
        raise RagSourceManifestError(f"RAG source id '{source_id}' is duplicated.")
    source_ids.add(source_id)

    for field in ("path", "collection", "family"):
        value = source[field]
        if not isinstance(value, str) or not value.strip():
            raise RagSourceManifestError(f"RAG source '{source_id}' has an invalid '{field}'.")

    collection = source["collection"]
    if not _is_valid_chroma_collection_name(collection):
        raise RagSourceManifestError(
            f"RAG source '{source_id}' has an invalid Chroma collection name '{collection}'."
        )

    include = source.get("include")
    if include is not None and (
        not isinstance(include, list) or not all(isinstance(item, str) and item.strip() for item in include)
    ):
        raise RagSourceManifestError(f"RAG source '{source_id}' has an invalid include list.")

    metadata = source["metadata"]
    if not isinstance(metadata, dict):
        raise RagSourceManifestError(f"RAG source '{source_id}' metadata must be a mapping.")

    missing_metadata = sorted(REQUIRED_METADATA_FIELDS - set(metadata))
    if missing_metadata:
        raise RagSourceManifestError(
            f"RAG source '{source_id}' metadata is missing required fields: {', '.join(missing_metadata)}."
        )

    for field in ("jurisdiction", "language"):
        value = metadata[field]
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise RagSourceManifestError(
                f"RAG source '{source_id}' metadata field '{field}' must be a list of strings."
            )


def _is_valid_chroma_collection_name(name: str) -> bool:
    """Return whether a collection name is compatible with Chroma naming rules."""
    if not CHROMA_COLLECTION_NAME_PATTERN.match(name):
        return False
    if ".." in name:
        return False
    parts = name.split(".")
    return not (len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts))
