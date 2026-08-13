from __future__ import annotations

from jsonschema import Draft202012Validator

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.nodes.manifest import NodeManifest
from ai_workflow.nodes.base import NodeResult


class NodeOutputError(ValueError):
    """Raised when a node result does not match its catalog output ports."""


def validate_node_outputs(manifest: NodeManifest, outputs: dict[str, JsonValue]) -> None:
    """Ensure required catalog output ports are present and schema-valid."""
    declared = {port.name: port for port in manifest.outputs}
    # Extra ports are allowed (condition/loop emit named branches).
    for name, port in declared.items():
        if port.required and name not in outputs:
            if any(other in outputs for other in declared if other != name):
                continue
            msg = f"Node {manifest.type} missing required output port {name!r}"
            raise NodeOutputError(msg)
        if name not in outputs:
            continue
        validator = Draft202012Validator(port.schema_)
        value = outputs[name]
        if port.cardinality == "multiple" and isinstance(value, list):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            errors = list(validator.iter_errors(candidate))
            if errors:
                msg = f"Node {manifest.type} output {name!r} failed schema: {errors[0].message}"
                raise NodeOutputError(msg)


def require_node_result(result: NodeResult, manifest: NodeManifest) -> NodeResult:
    validate_node_outputs(manifest, result.outputs)
    return result
