from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai_workflow.contracts.nodes.manifest import (
    ManifestValidationError,
    NodeManifest,
    manifest_from_dict,
)

_MANIFEST_SCHEMA: dict | None = None
_VALIDATOR: Draft202012Validator | None = None


def _manifest_schema_path(contracts_root: Path) -> Path:
    """Return the path to the node manifest JSON Schema file."""
    return contracts_root / "nodes" / "manifest.schema.json"


def _catalog_dir(contracts_root: Path) -> Path:
    """Return the directory containing catalog manifest JSON files."""
    return contracts_root / "nodes" / "catalog"


def load_manifest_schema(contracts_root: Path) -> dict:
    """Load and cache the node manifest JSON Schema."""
    global _MANIFEST_SCHEMA, _VALIDATOR
    if _MANIFEST_SCHEMA is None:
        schema_path = _manifest_schema_path(contracts_root)
        loaded: dict = json.loads(schema_path.read_text(encoding="utf-8"))
        _MANIFEST_SCHEMA = loaded
        _VALIDATOR = Draft202012Validator(loaded)
    return _MANIFEST_SCHEMA


def _get_validator(contracts_root: Path) -> Draft202012Validator:
    """Return a cached Draft 2020-12 validator for node manifest documents."""
    load_manifest_schema(contracts_root)
    assert _VALIDATOR is not None
    return _VALIDATOR


def validate_manifest_document(
    document: dict,
    *,
    contracts_root: Path,
    source: str = "<unknown>",
) -> None:
    """Validate a node manifest document against the manifest JSON Schema."""
    validator = _get_validator(contracts_root)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise ManifestValidationError(f"{source}: {location}: {first.message}")


def load_catalog_manifests(
    contracts_root: Path,
    *,
    catalog_dir: Path | None = None,
) -> dict[str, NodeManifest]:
    """Load, validate, and index every manifest in the node catalog directory."""
    directory = catalog_dir or _catalog_dir(contracts_root)
    if not directory.is_dir():
        msg = f"Catalog directory not found: {directory}"
        raise FileNotFoundError(msg)

    load_manifest_schema(contracts_root)
    manifests: dict[str, NodeManifest] = {}

    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        validate_manifest_document(raw, contracts_root=contracts_root, source=path.name)
        manifest = manifest_from_dict(raw)
        if manifest.type in manifests:
            msg = f"Duplicate manifest type in catalog: {manifest.type}"
            raise ManifestValidationError(msg)
        manifests[manifest.type] = manifest

    return manifests


def reset_manifest_schema_cache() -> None:
    """Clear cached manifest schema and validator state (for tests)."""
    global _MANIFEST_SCHEMA, _VALIDATOR
    _MANIFEST_SCHEMA = None
    _VALIDATOR = None
