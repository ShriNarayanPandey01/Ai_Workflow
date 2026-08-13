from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.bindings import json_pointer_get, json_pointer_set


class MergeNodeExecutor:
    node_type = "control.merge@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        del context
        mappings = config.get("mappings")
        if not isinstance(mappings, list) or not mappings:
            msg = "control.merge@1 requires non-empty config.mappings"
            raise ValueError(msg)

        on_conflict = config.get("on_conflict", "reject")
        if on_conflict not in {"reject", "first", "last"}:
            msg = f"Invalid on_conflict policy: {on_conflict!r}"
            raise ValueError(msg)

        result: JsonValue = {}
        claimed_targets: set[str] = set()

        for mapping in mappings:
            if not isinstance(mapping, dict):
                msg = "Each merge mapping must be an object"
                raise ValueError(msg)

            source_port = mapping.get("source_port")
            source_path = mapping.get("source_path")
            target_path = mapping.get("target_path")
            if (
                not isinstance(source_port, str)
                or not isinstance(source_path, str)
                or not isinstance(target_path, str)
            ):
                msg = "Merge mapping requires source_port, source_path, and target_path"
                raise ValueError(msg)

            if source_port not in inputs:
                msg = f"Merge source port {source_port!r} is missing"
                raise ValueError(msg)

            if target_path in claimed_targets:
                if on_conflict == "reject":
                    msg = f"Merge conflict on target path {target_path!r}"
                    raise ValueError(msg)
                if on_conflict == "first":
                    continue

            source_value = inputs[source_port]
            extracted = json_pointer_get(source_value, source_path)
            result = json_pointer_set(result, target_path, extracted)
            claimed_targets.add(target_path)

        return NodeResult(outputs={"value": result})
