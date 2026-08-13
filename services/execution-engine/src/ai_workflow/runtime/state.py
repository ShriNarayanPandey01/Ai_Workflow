from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from ai_workflow.contracts.common.types import JsonValue


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

    def get_port_value(self, node_id: str, port: str) -> JsonValue:
        """Return the value previously stored for a node output port."""
        return self.node_outputs[node_id][port]

    def snapshot(self) -> WorkflowState:
        """Return a deep copy safe for checkpoint persistence."""
        return deepcopy(self)
