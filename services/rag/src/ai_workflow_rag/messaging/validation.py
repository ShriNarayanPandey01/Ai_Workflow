from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

_VALIDATOR: Draft202012Validator | None = None
_VALIDATOR_ROOT: Path | None = None


class EnvelopeValidationError(Exception):
    """Raised when a message envelope fails JSON Schema validation."""


def _load_schema_file(path: Path) -> tuple[str, dict]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str):
        msg = f"Schema file missing $id: {path}"
        raise EnvelopeValidationError(msg)
    return schema_id, schema


def _build_registry(contracts_root: Path) -> Registry:
    resources: list[tuple[str, Any]] = []
    for schema_path in sorted(contracts_root.rglob("*.schema.json")):
        schema_id, schema = _load_schema_file(schema_path)
        resources.append((schema_id, DRAFT202012.create_resource(schema)))
    return Registry().with_resources(resources)


def load_envelope_validator(contracts_root: Path) -> Draft202012Validator:
    global _VALIDATOR, _VALIDATOR_ROOT
    if _VALIDATOR is not None and _VALIDATOR_ROOT == contracts_root:
        return _VALIDATOR
    envelope_path = contracts_root / "messages" / "envelope.schema.json"
    if not envelope_path.is_file():
        msg = f"Envelope schema not found: {envelope_path}"
        raise EnvelopeValidationError(msg)
    _, envelope_schema = _load_schema_file(envelope_path)
    registry = _build_registry(contracts_root)
    _VALIDATOR_ROOT = contracts_root
    _VALIDATOR = Draft202012Validator(envelope_schema, registry=registry)
    return _VALIDATOR


def validate_envelope_document(
    document: dict,
    *,
    contracts_root: Path,
    source: str = "<unknown>",
) -> None:
    validator = load_envelope_validator(contracts_root)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise EnvelopeValidationError(f"{source}: {location}: {first.message}")


def reset_envelope_schema_cache() -> None:
    global _VALIDATOR, _VALIDATOR_ROOT
    _VALIDATOR = None
    _VALIDATOR_ROOT = None
