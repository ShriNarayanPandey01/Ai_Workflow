from __future__ import annotations

from ai_workflow.runtime.graph.state import WorkflowState


def test_node_outputs_are_namespaced_by_node_id() -> None:
    state = WorkflowState()
    state.set_node_output("node-a", "value", {"order_id": "1"})
    state.set_node_output("node-b", "value", {"order_id": "2"})

    assert state.get_port_value("node-a", "value") == {"order_id": "1"}
    assert state.get_port_value("node-b", "value") == {"order_id": "2"}


def test_snapshot_is_independent_copy() -> None:
    state = WorkflowState()
    state.set_node_output("node-a", "value", {"count": 1})

    copy = state.snapshot()
    state.set_node_output("node-a", "value", {"count": 2})

    assert copy.get_port_value("node-a", "value") == {"count": 1}
