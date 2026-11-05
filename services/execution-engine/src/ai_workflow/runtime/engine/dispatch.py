from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.workflow.definition import WorkflowDefinition, WorkflowEdge, WorkflowNode
from ai_workflow.nodes.base import ExecutionContext, NodeResult, TransientNodeError
from ai_workflow.runtime.control.foreach import ForEachRuntime
from ai_workflow.runtime.engine.invoke import NodeInvoker
from ai_workflow.runtime.graph.interrupt import WorkflowInterrupt
from ai_workflow.runtime.graph.keys import RuntimeKeys
from ai_workflow.runtime.graph.scheduler import SchedulerSnapshot, save_interrupt
from ai_workflow.runtime.graph.state import WorkflowState
from ai_workflow.runtime.persistence.checkpoint import Checkpointer
from ai_workflow.runtime.registry import RuntimeRegistry
from ai_workflow.runtime.semantics.outputs import NodeOutputError
from ai_workflow.runtime.semantics.validator import SemanticValidator

if TYPE_CHECKING:
    from ai_workflow.runtime.cancel import CancelRegistry
    from ai_workflow.runtime.engine.engine import (
        TaskDispatcher,
        WorkflowRunWaiting,
    )
    from ai_workflow.security.credentials import CredentialResolver


class NodeDispatch(ABC):
    """Adapter the walker uses for a kind of node."""

    @abstractmethod
    def matches(self, node: WorkflowNode, *, durable: bool) -> bool: ...


class CollectInjectHandler:
    """Fills collect node inputs from runtime injection."""

    def apply(
        self,
        node: WorkflowNode,
        inputs: dict[str, JsonValue],
        state: WorkflowState,
    ) -> dict[str, JsonValue]:
        if node.type != "control.collect@1":
            return inputs
        items = state.collect_items_for(str(node.id))
        if items is not None:
            inputs["items"] = items
        return inputs


class DurableTaskHandler:
    """Checkpoints and dispatches a durable-task node."""

    async def run(
        self,
        *,
        node: WorkflowNode,
        inputs: dict[str, JsonValue],
        workflow: WorkflowDefinition,
        run_id: UUID,
        state: WorkflowState,
        scheduler: SchedulerSnapshot,
        checkpointer: Checkpointer,
        max_payload_bytes: int,
        task_dispatcher: TaskDispatcher,
        checkpoint_state: Callable[..., Awaitable[None]],
        waiting_factory: type[WorkflowRunWaiting],
    ) -> WorkflowRunWaiting:
        task_id = uuid4()
        interrupt_id = uuid4()
        state.task_refs[str(node.id)] = str(task_id)
        save_interrupt(
            state,
            interrupt_id=str(interrupt_id),
            waiting_reason="TASK",
            node_id=str(node.id),
            approval_id=None,
            node_type=node.type,
            approval_request={"task_type": node.type},
            task_id=str(task_id),
        )
        await checkpoint_state(
            checkpointer=checkpointer,
            run_id=run_id,
            state=state,
            scheduler=scheduler,
            max_payload_bytes=max_payload_bytes,
        )
        await task_dispatcher.start_task(
            run_id=run_id,
            node_id=node.id,
            task_type=node.type,
            payload=dict(inputs),
            credential_refs=dict(node.credential_refs),
            resource_refs=dict(node.resource_refs),
            budgets={
                "max_seconds": workflow.execution_policy.max_task_seconds,
                "max_items": 1,
                "max_provider_calls": workflow.execution_policy.max_provider_calls,
                "max_artifact_bytes": workflow.execution_policy.max_artifact_bytes,
            },
            task_id=task_id,
        )
        return waiting_factory(
            run_id=run_id,
            interrupt_id=interrupt_id,
            waiting_reason="TASK",
            state=state,
            node_id=node.id,
            approval_request={"task_id": str(task_id), "task_type": node.type},
        )


class InlineNodeHandler:
    """Invokes an inline node executor through NodeInvoker."""

    def __init__(self, invoker: NodeInvoker, semantic: SemanticValidator) -> None:
        self._invoker = invoker
        self._semantic = semantic

    def context_factory(
        self,
        *,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        run_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        deadline: datetime | None,
        runtime: dict[str, JsonValue],
        credential_resolver: CredentialResolver | None,
        cancel_registry: CancelRegistry | None,
    ) -> Callable[[int], ExecutionContext]:
        def factory(attempt: int) -> ExecutionContext:
            return ExecutionContext(
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                workflow_version_id=workflow.workflow_version_id,
                node_id=node.id,
                attempt=attempt,
                deadline=deadline,
                idempotency_key=f"{run_id}:{node.id}",
                runtime=runtime,
                input_schema=workflow.input_schema,
                output_schema=workflow.output_schema,
                credential_refs=dict(node.credential_refs),
                resource_refs=dict(node.resource_refs),
                credential_resolver=credential_resolver,
                cancel_check=(
                    cancel_registry.cancel_check(run_id)
                    if cancel_registry is not None
                    else (lambda: False)
                ),
            )

        return factory

    def build_runtime(self, state: WorkflowState) -> dict[str, JsonValue]:
        state_root = self._semantic.build_state_root(
            node_outputs=state.node_outputs,
            loop_iterations=state.loop_iterations,
            runtime=state.runtime,
        )
        runtime = dict(state.runtime)
        runtime[RuntimeKeys.STATE_ROOT] = state_root
        runtime[RuntimeKeys.LOOP_ITERATIONS] = dict(state.loop_iterations)
        return runtime

    async def invoke(
        self,
        *,
        registration,
        node: WorkflowNode,
        inputs: dict[str, JsonValue],
        retry,
        context_factory: Callable[[int], ExecutionContext],
    ) -> tuple[NodeResult, ExecutionContext]:
        return await self._invoker.invoke(
            registration=registration,
            context_factory=context_factory,
            config=node.config,
            inputs=inputs,
            retry=retry,
        )


class ForEachAfterHandler:
    """Thin adapter: after control.for-each@1, run ForEachRuntime."""

    def __init__(self, foreach: ForEachRuntime) -> None:
        self._foreach = foreach

    def matches(self, node: WorkflowNode) -> bool:
        return node.type == "control.for-each@1"

    async def run(
        self,
        *,
        workflow: WorkflowDefinition,
        registry: RuntimeRegistry,
        node_id: str,
        node: WorkflowNode,
        result: NodeResult,
        outgoing: dict[str, dict[str, list[WorkflowEdge]]],
        state: WorkflowState,
        scheduler: SchedulerSnapshot,
        checkpointer: Checkpointer,
        run_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        credential_resolver: object | None,
        cancel_registry: object | None,
        max_payload_bytes: int,
        max_parallel_nodes: int,
        try_enqueue: Callable[[str], None],
        checkpoint_state: Callable[..., Awaitable[None]],
        is_cancelled: Callable[[], Awaitable[str | None]],
        deadline: datetime | None,
    ) -> str | None:
        return await self._foreach.after_control_node(
            workflow=workflow,
            registry=registry,
            node_id=node_id,
            node=node,
            result=result,
            outgoing=outgoing,
            state=state,
            scheduler=scheduler,
            checkpointer=checkpointer,
            run_id=run_id,
            workspace_id=workspace_id,
            project_id=project_id,
            credential_resolver=credential_resolver,
            cancel_registry=cancel_registry,
            max_payload_bytes=max_payload_bytes,
            max_parallel_nodes=max_parallel_nodes,
            try_enqueue=try_enqueue,
            checkpoint_state=checkpoint_state,
            is_cancelled=is_cancelled,
            deadline=deadline,
        )


__all__ = [
    "CollectInjectHandler",
    "DurableTaskHandler",
    "ForEachAfterHandler",
    "InlineNodeHandler",
    "NodeDispatch",
    "NodeOutputError",
    "TransientNodeError",
    "WorkflowInterrupt",
]
