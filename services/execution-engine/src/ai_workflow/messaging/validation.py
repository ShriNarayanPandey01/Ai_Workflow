from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

_ENVELOPE_SCHEMA: dict | None = None
_VALIDATOR: Draft202012Validator | None = None
_VALIDATOR_ROOT: Path | None = None

ENVELOPE_SCHEMA_ID = "https://ai-workflow.local/contracts/messages/envelope.schema.json"


class EnvelopeValidationError(Exception):
    """Raised when a message envelope fails JSON Schema validation."""


def _load_schema_file(path: Path) -> tuple[str, dict]:
    """Load a JSON Schema file and return its ``$id`` and parsed document."""
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str):
        msg = f"Schema file missing $id: {path}"
        raise EnvelopeValidationError(msg)
    return schema_id, schema


def _build_registry(contracts_root: Path) -> Registry:
    """Build a JSON Schema registry from every ``*.schema.json`` under contracts."""
    resources: list[tuple[str, Any]] = []

    for schema_path in sorted(contracts_root.rglob("*.schema.json")):
        schema_id, schema = _load_schema_file(schema_path)
        resources.append((schema_id, DRAFT202012.create_resource(schema)))

    return Registry().with_resources(resources)


def load_envelope_validator(contracts_root: Path) -> Draft202012Validator:
    """Return a cached Draft 2020-12 validator for the envelope schema."""
    global _ENVELOPE_SCHEMA, _VALIDATOR, _VALIDATOR_ROOT

    if _VALIDATOR is not None and _VALIDATOR_ROOT == contracts_root:
        return _VALIDATOR

    envelope_path = contracts_root / "messages" / "envelope.schema.json"
    if not envelope_path.is_file():
        msg = f"Envelope schema not found: {envelope_path}"
        raise EnvelopeValidationError(msg)

    _, envelope_schema = _load_schema_file(envelope_path)
    registry = _build_registry(contracts_root)
    _ENVELOPE_SCHEMA = envelope_schema
    _VALIDATOR_ROOT = contracts_root
    _VALIDATOR = Draft202012Validator(envelope_schema, registry=registry)
    return _VALIDATOR


def validate_envelope_document(
    document: dict,
    *,
    contracts_root: Path,
    source: str = "<unknown>",
) -> None:
    """Validate a message envelope against the contracts envelope schema."""
    validator = load_envelope_validator(contracts_root)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise EnvelopeValidationError(f"{source}: {location}: {first.message}")


def reset_envelope_schema_cache() -> None:
    """Clear cached envelope schema and validator state (for tests)."""
    global _ENVELOPE_SCHEMA, _VALIDATOR, _VALIDATOR_ROOT
    _ENVELOPE_SCHEMA = None
    _VALIDATOR = None
    _VALIDATOR_ROOT = None
