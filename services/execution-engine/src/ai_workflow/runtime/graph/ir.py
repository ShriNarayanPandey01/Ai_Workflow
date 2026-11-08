from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ai_workflow.contracts.workflow.definition import WorkflowDefinition, WorkflowEdge, WorkflowNode
from ai_workflow.runtime.persistence.definition_store import hash_definition


@dataclass(frozen=True, slots=True)
class WorkflowIR:
    """Immutable interpreted-workflow cache entry (not a compiled executable)."""

    definition_hash: str
    workflow: WorkflowDefinition
    nodes_by_id: dict[str, WorkflowNode]
    outgoing: dict[str, dict[str, list[WorkflowEdge]]]


def _outgoing_by_port(workflow: WorkflowDefinition) -> dict[str, dict[str, list[WorkflowEdge]]]:
    outgoing: dict[str, dict[str, list[WorkflowEdge]]] = defaultdict(lambda: defaultdict(list))
    for edge in workflow.edges:
        outgoing[str(edge.source_node_id)][edge.source_port].append(edge)
    result: dict[str, dict[str, list[WorkflowEdge]]] = {
        str(node.id): dict(outgoing.get(str(node.id), {})) for node in workflow.nodes
    }
    return result


class WorkflowIRCache:
    """Process-local IR cache keyed by definition hash."""

    def __init__(self) -> None:
        self._entries: dict[str, WorkflowIR] = {}

    def get(self, workflow: WorkflowDefinition) -> WorkflowIR:
        document = workflow.model_dump(mode="json", exclude_none=True)
        digest = hash_definition(document)
        cached = self._entries.get(digest)
        if cached is not None:
            return cached
        ir = WorkflowIR(
            definition_hash=digest,
            workflow=workflow,
            nodes_by_id=workflow.node_by_id(),
            outgoing=_outgoing_by_port(workflow),
        )
        self._entries[digest] = ir
        return ir


_DEFAULT_IR_CACHE = WorkflowIRCache()


def build_workflow_ir(workflow: WorkflowDefinition) -> WorkflowIR:
    """Build an in-process IR for an immutable workflow definition."""
    return WorkflowIRCache().get(workflow)


def get_workflow_ir(workflow: WorkflowDefinition) -> WorkflowIR:
    """Return a cached IR for this definition hash, building it once per process."""
    return _DEFAULT_IR_CACHE.get(workflow)
