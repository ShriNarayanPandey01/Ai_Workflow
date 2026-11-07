from __future__ import annotations

from uuid import uuid4

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.graph.interrupt import WorkflowInterrupt


class HumanReviewNodeExecutor:
    """Pause execution until a human submits a reviewed value."""

    node_type = "human.review@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        value = inputs.get("value")
        if value is None:
            msg = "human.review@1 requires input port 'value'"
            raise ValueError(msg)

        allowed_schema = config.get("allowed_response_schema")
        if not isinstance(allowed_schema, dict) or not allowed_schema:
            msg = "human.review@1 requires config.allowed_response_schema"
            raise ValueError(msg)

        interrupt_id = uuid4()
        approval_id = uuid4()
        raise WorkflowInterrupt(
            interrupt_id=interrupt_id,
            waiting_reason="HUMAN",
            node_id=context.node_id,
            approval_id=approval_id,
            node_type=self.node_type,
            approval_request={
                "request_payload": value,
                "allowed_response_schema": allowed_schema,
            },
        )
