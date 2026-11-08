from __future__ import annotations

from jsonschema import Draft202012Validator

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.nodes.manifest import NodeManifest
from ai_workflow.nodes.base import NodeResult


class NodeOutputError(ValueError):
    """Raised when a node result does not match its catalog output ports."""


class NodeOutputContract:
    """Validates node results against catalog output port schemas."""

    def validate(self, manifest: NodeManifest, outputs: dict[str, JsonValue]) -> None:
        declared = {port.name: port for port in manifest.outputs}
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
                    msg = (
                        f"Node {manifest.type} output {name!r} failed schema: "
                        f"{errors[0].message}"
                    )
                    raise NodeOutputError(msg)

    def require_result(self, result: NodeResult, manifest: NodeManifest) -> NodeResult:
        self.validate(manifest, result.outputs)
        return result


def validate_node_outputs(manifest: NodeManifest, outputs: dict[str, JsonValue]) -> None:
    NodeOutputContract().validate(manifest, outputs)


def require_node_result(result: NodeResult, manifest: NodeManifest) -> NodeResult:
    return NodeOutputContract().require_result(result, manifest)
