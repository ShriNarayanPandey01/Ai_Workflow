from ai_workflow.contracts.workflow.definition import WorkflowNode
from ai_workflow.runtime.graph.state import WorkflowState


def collect_is_ready(node: WorkflowNode, state: WorkflowState | None) -> bool:
    """Return whether a collect node may run (runtime item injection present)."""
    if state is None:
        return node.type != "control.collect@1"
    return state.collect_is_ready(node.type, str(node.id))
