from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.condition import evaluate_condition


class LoopNodeExecutor:
    node_type = "control.loop@1"

    def __init__(self, *, platform_max_iterations: int = 100) -> None:
        self._platform_max_iterations = platform_max_iterations

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        if "iteration" not in inputs:
            msg = "control.loop@1 requires input port 'iteration'"
            raise ValueError(msg)

        max_iterations = config.get("max_iterations")
        if not isinstance(max_iterations, int) or max_iterations < 1:
            msg = "control.loop@1 requires max_iterations >= 1"
            raise ValueError(msg)

        effective_max = min(max_iterations, self._platform_max_iterations)
        on_limit = config.get("on_limit", "done")
        if on_limit not in {"done", "fail"}:
            msg = f"Invalid on_limit policy: {on_limit!r}"
            raise ValueError(msg)

        iteration = inputs["iteration"]
        node_key = str(context.node_id)

        counters = context.runtime.setdefault("_loop_iterations", {})
        if not isinstance(counters, dict):
            counters = {}
            context.runtime["_loop_iterations"] = counters

        current = counters.get(node_key, 0)
        if not isinstance(current, int):
            current = 0
        current += 1
        counters[node_key] = current

        if current > effective_max:
            if on_limit == "fail":
                msg = (
                    f"Loop {node_key} exceeded max_iterations "
                    f"({effective_max})"
                )
                raise ValueError(msg)
            return NodeResult(
                outputs={
                    "done": {
                        "value": iteration,
                        "limit_reached": True,
                        "iterations": current - 1,
                    }
                }
            )

        exit_condition = config.get("exit_condition")
        if isinstance(exit_condition, dict):
            state_root = context.runtime.get("_state_root")
            if not isinstance(state_root, dict):
                msg = "Missing _state_root for loop exit_condition"
                raise ValueError(msg)
            # Expose iteration payload under /loop for exit AST paths.
            eval_root = dict(state_root)
            eval_root["loop"] = iteration if isinstance(iteration, dict) else {"value": iteration}
            if evaluate_condition(exit_condition, eval_root):
                return NodeResult(
                    outputs={
                        "done": {
                            "value": iteration,
                            "limit_reached": False,
                            "iterations": current,
                        }
                    }
                )

        return NodeResult(outputs={"body": iteration})
