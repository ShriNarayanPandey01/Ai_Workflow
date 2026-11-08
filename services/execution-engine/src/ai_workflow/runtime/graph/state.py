from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.runtime.graph.keys import RuntimeKeys


@dataclass
class WorkflowState:
    """Mutable in-memory workflow execution state."""

    node_outputs: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    loop_iterations: dict[str, int] = field(default_factory=dict)
    task_refs: dict[str, str] = field(default_factory=dict)
    runtime: dict[str, JsonValue] = field(default_factory=dict)

    def set_node_output(self, node_id: str, port: str, value: JsonValue) -> None:
        """Store a single output port value for a node."""
        ports = self.node_outputs.setdefault(node_id, {})
        ports[port] = value

    def set_node_outputs(self, node_id: str, outputs: dict[str, JsonValue]) -> None:
        """Store all output port values for a node."""
        for port, value in outputs.items():
            self.set_node_output(node_id, port, value)

    def record_node_outputs(self, node_id: str, outputs: dict[str, JsonValue]) -> None:
        """Replace all output ports for a node."""
        self.node_outputs[node_id] = dict(outputs)

    def get_port_value(self, node_id: str, port: str) -> JsonValue:
        """Return the value previously stored for a node output port."""
        return self.node_outputs[node_id][port]

    def inject_collect_items(self, node_id: str, items: JsonValue) -> None:
        inject = self.runtime.setdefault(RuntimeKeys.COLLECT_INJECT, {})
        if not isinstance(inject, dict):
            inject = {}
            self.runtime[RuntimeKeys.COLLECT_INJECT] = inject
        inject[node_id] = items

    def collect_items_for(self, node_id: str) -> JsonValue | None:
        inject = self.runtime.get(RuntimeKeys.COLLECT_INJECT)
        if not isinstance(inject, dict) or node_id not in inject:
            return None
        return inject[node_id]

    def collect_is_ready(self, node_type: str, node_id: str) -> bool:
        if node_type != "control.collect@1":
            return True
        return self.collect_items_for(node_id) is not None

    def set_interrupt(
        self,
        *,
        interrupt_id: str,
        waiting_reason: str,
        node_id: str,
        approval_id: str | None,
        node_type: str,
        approval_request: dict[str, JsonValue],
        task_id: str | None = None,
    ) -> None:
        self.runtime[RuntimeKeys.INTERRUPT] = {
            "interrupt_id": interrupt_id,
            "waiting_reason": waiting_reason,
            "node_id": node_id,
            "approval_id": approval_id,
            "node_type": node_type,
            "approval_request": approval_request,
            "task_id": task_id,
        }

    def interrupt(self) -> dict[str, Any] | None:
        raw = self.runtime.get(RuntimeKeys.INTERRUPT)
        return raw if isinstance(raw, dict) else None

    def clear_interrupt(self) -> None:
        self.runtime.pop(RuntimeKeys.INTERRUPT, None)

    def merge_loop_iterations(self, counters: dict[str, Any]) -> None:
        for key, value in counters.items():
            if isinstance(value, int):
                self.loop_iterations[str(key)] = value

    def snapshot(self) -> WorkflowState:
        """Return a deep copy safe for checkpoint persistence."""
        return deepcopy(self)
