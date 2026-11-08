from __future__ import annotations

from uuid import uuid4

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.graph.interrupt import WorkflowInterrupt


class HumanApprovalNodeExecutor:
    """Pause execution until a human approves or rejects a request payload."""

    node_type = "human.approval@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        request = inputs.get("request")
        if request is None:
            msg = "human.approval@1 requires input port 'request'"
            raise ValueError(msg)

        allowed_schema = config.get("allowed_response_schema")
        if not isinstance(allowed_schema, dict) or not allowed_schema:
            msg = "human.approval@1 requires config.allowed_response_schema"
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
                "request_payload": request,
                "allowed_response_schema": allowed_schema,
            },
        )
