from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.checkpoint import InMemoryCheckpointer
from ai_workflow.runtime.runner import (
    WorkflowRunCancelled,
    WorkflowRunCompleted,
    continue_workflow_from_checkpoint,
    run_workflow,
)


@pytest.mark.asyncio
async def test_cancel_registry_flags_run() -> None:
    registry = CancelRegistry()
    run_id = UUID("44444444-4444-4444-8444-444444444401")
    assert await registry.is_cancelled(run_id) is None
    await registry.request_cancel(run_id, reason="user_requested")
    request = await registry.is_cancelled(run_id)
    assert request is not None
    assert request.reason == "user_requested"
    await registry.clear(run_id)
    assert await registry.is_cancelled(run_id) is None


@pytest.mark.asyncio
async def test_run_cancels_before_next_node(
    repo_contracts_root,
    workflow_linear_definition: dict,
) -> None:
    from ai_workflow.runtime.bootstrap import build_runner_registry

    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    cancel_registry = CancelRegistry()
    run_id = UUID("44444444-4444-4444-8444-444444444401")

    await cancel_registry.request_cancel(run_id, reason="user_requested")
    outcome = await run_workflow(
        workflow_linear_definition,
        {"order_id": "ord-cancel"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        cancel_registry=cancel_registry,
    )

    assert isinstance(outcome, WorkflowRunCancelled)
    assert outcome.reason == "user_requested"


@pytest.mark.asyncio
async def test_continue_from_checkpoint_after_partial_run(
    repo_contracts_root,
    workflow_linear_definition: dict,
) -> None:
    from ai_workflow.runtime.bootstrap import build_runner_registry

    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("44444444-4444-4444-8444-444444444402")

    first = await run_workflow(
        workflow_linear_definition,
        {"order_id": "ord-restart"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(first, WorkflowRunCompleted)

    checkpoint = await checkpointer.load(thread_id=run_id)
    assert checkpoint is not None

    second = await continue_workflow_from_checkpoint(
        workflow_linear_definition,
        run_id=run_id,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(second, WorkflowRunCompleted)
    assert second.output == {"order_id": "ord-restart"}


@pytest.mark.asyncio
async def test_late_result_is_discarded_when_cancelled(
    repo_contracts_root,
    workflow_linear_definition: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workflow.nodes.data.input import InputNodeExecutor
    from ai_workflow.runtime.bootstrap import build_runner_registry

    run_id = UUID("44444444-4444-4444-8444-444444444405")
    cancel_registry = CancelRegistry()
    original = InputNodeExecutor.execute

    async def _cancel_then_return(self, context, config, inputs):  # type: ignore[no-untyped-def]
        await cancel_registry.request_cancel(run_id, reason="user_requested")
        return await original(self, context, config, inputs)

    monkeypatch.setattr(InputNodeExecutor, "execute", _cancel_then_return)
    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    outcome = await run_workflow(
        workflow_linear_definition,
        {"order_id": "ord-late"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        cancel_registry=cancel_registry,
    )
    assert isinstance(outcome, WorkflowRunCancelled)
    checkpoint = await checkpointer.load(thread_id=run_id)
    assert checkpoint is not None
    assert "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1" not in checkpoint.node_outputs


@pytest.mark.asyncio
async def test_continue_from_checkpoint_mid_run(
    repo_contracts_root,
    workflow_linear_definition: dict,
) -> None:
    from ai_workflow.runtime.bootstrap import build_runner_registry

    class _CountingCheckpointer(InMemoryCheckpointer):
        def __init__(self) -> None:
            super().__init__()
            self.saves = 0
            self.first_saved = asyncio.Event()

        async def save(self, *, thread_id: UUID, state) -> None:  # type: ignore[no-untyped-def]
            await super().save(thread_id=thread_id, state=state)
            self.saves += 1
            if self.saves == 1:
                self.first_saved.set()

    registry = build_runner_registry(repo_contracts_root)
    checkpointer = _CountingCheckpointer()
    run_id = UUID("44444444-4444-4444-8444-444444444406")

    task = asyncio.create_task(
        run_workflow(
            workflow_linear_definition,
            {"order_id": "ord-mid"},
            registry=registry,
            run_id=run_id,
            checkpointer=checkpointer,
            contracts_root=repo_contracts_root,
        )
    )
    await asyncio.wait_for(checkpointer.first_saved.wait(), timeout=2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    resumed = await continue_workflow_from_checkpoint(
        workflow_linear_definition,
        run_id=run_id,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(resumed, WorkflowRunCompleted)
    assert resumed.output == {"order_id": "ord-mid"}
