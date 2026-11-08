from __future__ import annotations

from typing import Any


def schema_at_pointer(schema: dict[str, Any], pointer: str) -> dict[str, Any] | None:
    """Resolve a JSON Schema subschema at a JSON Pointer path into instance data."""
    if pointer in {"", "/"}:
        return schema

    if not pointer.startswith("/"):
        return None

    current: dict[str, Any] = schema
    for token in pointer.lstrip("/").split("/"):
        if not isinstance(current, dict):
            return None

        if token.isdigit():
            items = current.get("items")
            if not isinstance(items, dict):
                return None
            current = items
            continue

        properties = current.get("properties")
        if not isinstance(properties, dict) or token not in properties:
            return None
        nested = properties[token]
        if not isinstance(nested, dict):
            return None
        current = nested

    return current


def _schema_types(schema: dict[str, Any]) -> set[str] | None:
    """Return declared JSON Schema types, or None when unconstrained."""
    raw_type = schema.get("type")
    if raw_type is None:
        return None
    if isinstance(raw_type, str):
        return {raw_type}
    if isinstance(raw_type, list):
        return {item for item in raw_type if isinstance(item, str)}
    return None


def _enum_values(schema: dict[str, Any]) -> set[Any] | None:
    """Return enum or const values when declared."""
    if "enum" in schema and isinstance(schema["enum"], list):
        return set(schema["enum"])
    if "const" in schema:
        return {schema["const"]}
    return None


def schemas_compatible(source: dict[str, Any], target: dict[str, Any]) -> bool:
    """Check pragmatic type compatibility between catalog port subschemas."""
    source_types = _schema_types(source)
    target_types = _schema_types(target)

    if source_types is None or target_types is None:
        return True

    if source_types == target_types:
        compatible = True
    elif source_types <= {"integer", "number"} and target_types <= {"integer", "number"}:
        compatible = "number" in target_types or source_types == {"integer"}
    else:
        compatible = False

    if not compatible:
        return False

    target_enum = _enum_values(target)
    if target_enum is None:
        return True

    source_enum = _enum_values(source)
    if source_enum is None:
        return True

    return source_enum.issubset(target_enum)
