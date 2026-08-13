from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from ai_workflow.runtime.bootstrap import build_runner_registry
from ai_workflow.runtime.checkpoint import InMemoryCheckpointer
from ai_workflow.runtime.runner import WorkflowRunWaiting, run_workflow
from ai_workflow.runtime.scheduler_state import get_interrupt


class _RecordingDispatcher:
    def __init__(self, checkpointer: InMemoryCheckpointer, run_id: UUID) -> None:
        self._checkpointer = checkpointer
        self._run_id = run_id
        self.interrupt_at_dispatch: dict | None = None
        self.task_id: UUID | None = None

    async def start_task(self, **kwargs):
        self.task_id = kwargs.get("task_id")
        state = await self._checkpointer.load(thread_id=self._run_id)
        self.interrupt_at_dispatch = get_interrupt(state) if state is not None else None
        return self.task_id or uuid4()


@pytest.mark.asyncio
async def test_durable_task_is_checkpointed_before_dispatch(
    repo_contracts_root,
) -> None:
    definition = json.loads(
        (
            repo_contracts_root / "fixtures" / "valid" / "workflow-e2e-durable-task.json"
        ).read_text(encoding="utf-8")
    )
    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = uuid4()
    dispatcher = _RecordingDispatcher(checkpointer, run_id)

    outcome = await run_workflow(
        definition,
        {"question": "What is a durable workflow task?"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        task_dispatcher=dispatcher,
    )

    assert isinstance(outcome, WorkflowRunWaiting)
    assert outcome.waiting_reason == "TASK"
    assert dispatcher.interrupt_at_dispatch is not None
    assert dispatcher.interrupt_at_dispatch.get("waiting_reason") == "TASK"
    assert dispatcher.interrupt_at_dispatch.get("task_id") == str(dispatcher.task_id)
