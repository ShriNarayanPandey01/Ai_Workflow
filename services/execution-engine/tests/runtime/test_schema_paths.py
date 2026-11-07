from __future__ import annotations

from ai_workflow.runtime.semantics.schema_paths import schema_at_pointer, schemas_compatible


def test_schema_at_pointer_nested_property() -> None:
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "messages": {"type": "array"},
        },
    }

    assert schema_at_pointer(schema, "/text") == {"type": "string"}
    assert schema_at_pointer(schema, "/messages") == {"type": "array"}
    assert schema_at_pointer(schema, "/missing") is None


def test_schemas_compatible_accepts_matching_types() -> None:
    assert schemas_compatible({"type": "string"}, {"type": "string"})
    assert schemas_compatible({"type": "integer"}, {"type": "number"})


def test_schemas_compatible_rejects_obvious_mismatch() -> None:
    assert not schemas_compatible({"type": "string"}, {"type": "object"})
    assert not schemas_compatible({"type": "array"}, {"type": "string"})


def test_schemas_compatible_respects_target_enum() -> None:
    source = {"type": "string", "enum": ["a"]}
    target = {"type": "string", "enum": ["a", "b"]}
    bad_source = {"type": "string", "enum": ["c"]}

    assert schemas_compatible(source, target)
    assert not schemas_compatible(bad_source, target)
