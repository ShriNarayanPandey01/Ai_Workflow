from __future__ import annotations

from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.nodes.data.input import _validate_schema


class OutputNodeExecutor:
    node_type = "data.output@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict,
        inputs: dict,
    ) -> NodeResult:
        del config
        if "value" not in inputs:
            msg = "Missing required input port 'value'"
            raise ValueError(msg)

        value = inputs["value"]
        _validate_schema(value, context.output_schema, label="workflow output")
        return NodeResult(outputs={"value": value})
