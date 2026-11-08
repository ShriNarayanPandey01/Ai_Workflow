from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.semantics.condition import evaluate_condition


class ConditionNodeExecutor:
    node_type = "control.condition@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        condition = config.get("condition")
        if not isinstance(condition, dict):
            msg = "control.condition@1 requires config.condition AST"
            raise ValueError(msg)

        state_root = context.runtime.get("_state_root")
        if not isinstance(state_root, dict):
            msg = "Missing _state_root in execution context for condition evaluation"
            raise ValueError(msg)

        result = evaluate_condition(condition, state_root)
        payload = inputs.get("value", {})
        branch = "true" if result else "false"
        return NodeResult(outputs={branch: payload})
