from __future__ import annotations

from uuid import UUID

import pytest

from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.nodes.human.approval import HumanApprovalNodeExecutor
from ai_workflow.nodes.human.review import HumanReviewNodeExecutor
from ai_workflow.runtime.checkpoint import InMemoryCheckpointer
from ai_workflow.runtime.interrupt import WorkflowInterrupt
from ai_workflow.runtime.runner import (
    ResumeValidationError,
    WorkflowRunCompleted,
    WorkflowRunWaiting,
    resume_workflow,
    run_workflow,
)
from ai_workflow.runtime.scheduler_state import get_interrupt


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id=UUID("44444444-4444-4444-8444-444444444401"),
        workspace_id=UUID("11111111-1111-4111-8111-111111111101"),
        project_id=UUID("66666666-6666-4666-8666-666666666601"),
        workflow_version_id=UUID("22222222-2222-4222-8222-222222222201"),
        node_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaab02"),
        attempt=1,
    )


@pytest.mark.asyncio
async def test_approval_executor_raises_interrupt() -> None:
    executor = HumanApprovalNodeExecutor()
    with pytest.raises(WorkflowInterrupt) as exc_info:
        await executor.execute(
            _context(),
            {"allowed_response_schema": {"type": "object"}},
            {"request": {"action": "deploy"}},
        )
    interrupt = exc_info.value
    assert interrupt.waiting_reason == "HUMAN"
    assert interrupt.node_type == "human.approval@1"


@pytest.mark.asyncio
async def test_review_executor_raises_interrupt() -> None:
    executor = HumanReviewNodeExecutor()
    with pytest.raises(WorkflowInterrupt) as exc_info:
        await executor.execute(
            _context(),
            {"allowed_response_schema": {"type": "object"}},
            {"value": {"draft": "v1"}},
        )
    assert exc_info.value.node_type == "human.review@1"


@pytest.mark.asyncio
async def test_human_approval_workflow_waits_then_resumes(
    repo_contracts_root,
    workflow_human_approval_definition: dict,
) -> None:
    from ai_workflow.runtime.bootstrap import build_runner_registry

    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("44444444-4444-4444-8444-444444444403")
    run_input = {"action": "deploy", "amount": 100}

    waiting = await run_workflow(
        workflow_human_approval_definition,
        run_input,
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(waiting, WorkflowRunWaiting)
    assert waiting.waiting_reason == "HUMAN"

    checkpoint = await checkpointer.load(thread_id=run_id)
    assert checkpoint is not None
    interrupt = get_interrupt(checkpoint)
    assert interrupt is not None

    completed = await resume_workflow(
        run_id=run_id,
        waiting_reason="HUMAN",
        interrupt_id=UUID(str(interrupt["interrupt_id"])),
        approval_id=UUID(str(interrupt["approval_id"])),
        task_id=None,
        decision={"decision": "approved", "data": {"note": "ok"}},
        definition=workflow_human_approval_definition,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(completed, WorkflowRunCompleted)
    assert completed.output == {
        "decision": "approved",
        "data": {"note": "ok"},
    }


@pytest.mark.asyncio
async def test_resume_rejects_wrong_interrupt_id(
    repo_contracts_root,
    workflow_human_approval_definition: dict,
) -> None:
    from ai_workflow.runtime.bootstrap import build_runner_registry

    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("44444444-4444-4444-8444-444444444404")

    waiting = await run_workflow(
        workflow_human_approval_definition,
        {"action": "deploy"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(waiting, WorkflowRunWaiting)

    checkpoint = await checkpointer.load(thread_id=run_id)
    assert checkpoint is not None
    interrupt = get_interrupt(checkpoint)
    assert interrupt is not None

    with pytest.raises(ResumeValidationError, match="interrupt_id"):
        await resume_workflow(
            run_id=run_id,
            waiting_reason="HUMAN",
            interrupt_id=UUID("00000000-0000-4000-8000-000000000001"),
            approval_id=UUID(str(interrupt["approval_id"])),
            task_id=None,
            decision={"decision": "approved"},
            definition=workflow_human_approval_definition,
            registry=registry,
            checkpointer=checkpointer,
            contracts_root=repo_contracts_root,
        )


@pytest.mark.asyncio
async def test_waiting_survives_fresh_checkpointer_and_resume_only(
    repo_contracts_root,
    workflow_human_approval_definition: dict,
) -> None:
    from ai_workflow.runtime.bootstrap import build_runner_registry
    from ai_workflow.runtime.runner import continue_workflow_from_checkpoint

    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("44444444-4444-4444-8444-444444444407")

    waiting = await run_workflow(
        workflow_human_approval_definition,
        {"action": "deploy"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(waiting, WorkflowRunWaiting)

    stored = await checkpointer.load(thread_id=run_id)
    assert stored is not None
    fresh = InMemoryCheckpointer()
    await fresh.save(thread_id=run_id, state=stored)
    interrupt = get_interrupt(stored)
    assert interrupt is not None

    with pytest.raises(Exception, match="waiting for resume"):
        await continue_workflow_from_checkpoint(
            workflow_human_approval_definition,
            run_id=run_id,
            registry=registry,
            checkpointer=fresh,
            contracts_root=repo_contracts_root,
        )

    completed = await resume_workflow(
        run_id=run_id,
        waiting_reason="HUMAN",
        interrupt_id=UUID(str(interrupt["interrupt_id"])),
        approval_id=UUID(str(interrupt["approval_id"])),
        task_id=None,
        decision={"decision": "approved", "data": {"note": "ok"}},
        definition=workflow_human_approval_definition,
        registry=registry,
        checkpointer=fresh,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(completed, WorkflowRunCompleted)
