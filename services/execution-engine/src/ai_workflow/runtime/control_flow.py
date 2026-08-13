from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from ai_workflow.contracts.workflow.definition import WorkflowDefinition, WorkflowEdge, WorkflowNode
from ai_workflow.nodes.base import NodeResult
from ai_workflow.runtime.checkpoint import Checkpointer
from ai_workflow.runtime.for_each_runtime import (
    COLLECT_INJECT_KEY,
    ForEachFrame,
    build_frame_from_outputs,
    load_foreach_frames,
    run_foreach_frame,
    save_foreach_frames,
)
from ai_workflow.runtime.registry import RuntimeRegistry
from ai_workflow.runtime.scheduler_state import SchedulerSnapshot
from ai_workflow.runtime.state import WorkflowState

if TYPE_CHECKING:
    from ai_workflow.runtime.cancel import CancelRegistry
    from ai_workflow.runtime.runner import WorkflowRunCancelled, WorkflowRunHooks


def collect_is_ready(node: WorkflowNode, state: WorkflowState | None) -> bool:
    """Return whether a collect node may run (runtime item injection present)."""
    if node.type != "control.collect@1":
        return True
    if state is None:
        return False
    inject_raw = state.runtime.get(COLLECT_INJECT_KEY)
    return isinstance(inject_raw, dict) and str(node.id) in inject_raw


async def handle_foreach_after_execute(
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
    cancel_registry: CancelRegistry | None,
    max_payload_bytes: int,
    max_parallel_nodes: int,
    try_enqueue: Callable[[str], None],
    checkpoint_state: Callable[..., Awaitable[None]],
    is_cancelled: Callable[[], Awaitable[str | None]],
    hooks: WorkflowRunHooks | None,
    cancelled_factory: Callable[..., WorkflowRunCancelled],
    existing_frame: ForEachFrame | None = None,
    deadline: datetime | None = None,
) -> WorkflowRunCancelled | None:
    """Run the for-each item body after the control node emits envelopes."""
    frame = existing_frame
    if frame is None or frame.completed:
        frame = build_frame_from_outputs(
            workflow=workflow,
            for_each_node_id=node_id,
            node_config=node.config,
            outputs=dict(result.outputs),
            outgoing=outgoing,
            max_parallel_nodes=max_parallel_nodes,
        )
    if frame is None:
        return None

    frames = load_foreach_frames(state)

    async def _persist_frame_progress(
        current_frame: ForEachFrame,
        *,
        _frames: dict[str, ForEachFrame] = frames,
        _node_id: str = node_id,
    ) -> None:
        _frames[_node_id] = current_frame
        save_foreach_frames(state, _frames)
        await checkpoint_state(
            checkpointer=checkpointer,
            run_id=run_id,
            state=state,
            scheduler=scheduler,
            max_payload_bytes=max_payload_bytes,
        )

    try:
        frame = await run_foreach_frame(
            workflow=workflow,
            registry=registry,
            frame=frame,
            state=state,
            run_id=run_id,
            workspace_id=workspace_id,
            project_id=project_id,
            credential_resolver=credential_resolver,
            cancel_check=(
                cancel_registry.event_for(run_id) if cancel_registry is not None else None
            ),
            on_item_complete=_persist_frame_progress,
            deadline=deadline,
        )
    except Exception as exc:
        msg = f"For-each subflow failed for node {node.id}: {exc}"
        if hooks is not None:
            await hooks.on_node_failed(node_id=node.id, node_type=node.type, error=str(exc))
        raise RuntimeError(msg) from exc

    frames[node_id] = frame
    save_foreach_frames(state, frames)
    await checkpoint_state(
        checkpointer=checkpointer,
        run_id=run_id,
        state=state,
        scheduler=scheduler,
        max_payload_bytes=max_payload_bytes,
    )
    cancel_reason = await is_cancelled()
    if cancel_reason is not None:
        return cancelled_factory(run_id=run_id, reason=cancel_reason, state=state)
    try_enqueue(frame.collect_node_id)
    return None


async def resume_incomplete_foreach_frames(
    *,
    workflow: WorkflowDefinition,
    registry: RuntimeRegistry,
    outgoing: dict[str, dict[str, list[WorkflowEdge]]],
    nodes_by_id: dict[str, WorkflowNode],
    state: WorkflowState,
    scheduler: SchedulerSnapshot,
    checkpointer: Checkpointer,
    run_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    credential_resolver: object | None,
    cancel_registry: CancelRegistry | None,
    max_payload_bytes: int,
    max_parallel_nodes: int,
    try_enqueue: Callable[[str], None],
    checkpoint_state: Callable[..., Awaitable[None]],
    is_cancelled: Callable[[], Awaitable[str | None]],
    hooks: WorkflowRunHooks | None,
    cancelled_factory: Callable[..., WorkflowRunCancelled],
    deadline: datetime | None = None,
) -> WorkflowRunCancelled | None:
    """Re-enter for-each bodies that were checkpointed before completion."""
    frames = load_foreach_frames(state)
    for node in workflow.nodes:
        if node.type != "control.for-each@1":
            continue
        node_id = str(node.id)
        outputs = state.node_outputs.get(node_id)
        if not isinstance(outputs, dict) or not outputs:
            continue
        existing = frames.get(node_id)
        if existing is not None and existing.completed:
            if existing.collect_node_id not in state.node_outputs:
                try_enqueue(existing.collect_node_id)
            continue
        cancelled = await handle_foreach_after_execute(
            workflow=workflow,
            registry=registry,
            node_id=node_id,
            node=nodes_by_id[node_id],
            result=NodeResult(outputs=dict(outputs)),
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
            hooks=hooks,
            cancelled_factory=cancelled_factory,
            existing_frame=existing,
            deadline=deadline,
        )
        if cancelled is not None:
            return cancelled
    return None
