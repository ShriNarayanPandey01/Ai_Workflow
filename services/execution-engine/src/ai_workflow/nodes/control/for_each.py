from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.nodes.control.item_keys import parse_items_input, stable_item_key


class ForEachNodeExecutor:
    node_type = "control.for-each@1"

    def __init__(self, *, platform_max_fan_out_items: int = 1000) -> None:
        self._platform_max_fan_out_items = platform_max_fan_out_items

    def _effective_max(
        self,
        config: dict[str, JsonValue],
        context: ExecutionContext,
    ) -> int:
        max_items = config.get("max_items")
        if not isinstance(max_items, int) or max_items < 1:
            msg = "control.for-each@1 requires max_items >= 1"
            raise ValueError(msg)

        policy_cap = context.runtime.get("_max_fan_out_items")
        if isinstance(policy_cap, int) and policy_cap >= 1:
            return min(max_items, policy_cap, self._platform_max_fan_out_items)
        return min(max_items, self._platform_max_fan_out_items)

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        if "items" not in inputs:
            msg = "control.for-each@1 requires input port 'items'"
            raise ValueError(msg)

        for key in ("concurrency", "item_timeout_seconds", "ordering", "failure_policy"):
            if key not in config:
                msg = f"control.for-each@1 requires config.{key}"
                raise ValueError(msg)

        ordering = config["ordering"]
        if ordering not in {"preserve_input", "completion_order"}:
            msg = f"Invalid ordering policy: {ordering!r}"
            raise ValueError(msg)

        failure_policy = config["failure_policy"]
        if failure_policy not in {"fail_fast", "continue"}:
            msg = f"Invalid failure_policy: {failure_policy!r}"
            raise ValueError(msg)

        if not isinstance(config["concurrency"], int) or config["concurrency"] < 1:
            msg = "control.for-each@1 requires concurrency >= 1"
            raise ValueError(msg)

        if (
            not isinstance(config["item_timeout_seconds"], int)
            or config["item_timeout_seconds"] < 1
        ):
            msg = "control.for-each@1 requires item_timeout_seconds >= 1"
            raise ValueError(msg)

        items = parse_items_input(inputs["items"])
        effective_max = self._effective_max(config, context)
        if len(items) > effective_max:
            msg = (
                f"Item count {len(items)} exceeds effective max_items cap "
                f"({effective_max})"
            )
            raise ValueError(msg)

        envelopes: list[JsonValue] = []
        for index, item in enumerate(items):
            envelopes.append(
                {
                    "item": item,
                    "item_key": stable_item_key(index, item),
                    "index": index,
                }
            )

        return NodeResult(
            outputs={
                "item": envelopes,
                "done": {"count": len(envelopes)},
            }
        )
