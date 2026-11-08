from __future__ import annotations

from uuid import uuid4

import pytest

from ai_workflow.runtime.pause import PauseRegistry


@pytest.mark.asyncio
async def test_pause_revisions_prevent_stale_or_mismatched_resume() -> None:
    registry = PauseRegistry()
    run_id, pause_id, other_pause = uuid4(), uuid4(), uuid4()

    assert await registry.apply(run_id, pause_id=pause_id, revision=1, requested=True)
    assert not await registry.apply(run_id, pause_id=other_pause, revision=2, requested=False)
    assert not await registry.apply(run_id, pause_id=pause_id, revision=1, requested=True)
    assert (await registry.get(run_id)).requested  # type: ignore[union-attr]

    assert await registry.apply(run_id, pause_id=pause_id, revision=2, requested=False)
    assert not await registry.apply(run_id, pause_id=pause_id, revision=1, requested=True)
    assert not (await registry.get(run_id)).requested  # type: ignore[union-attr]
    assert await registry.apply(run_id, pause_id=other_pause, revision=3, requested=True)
    assert not await registry.apply(run_id, pause_id=pause_id, revision=4, requested=False)
    state = await registry.get(run_id)
    assert state is not None and state.pause_id == other_pause and state.requested


@pytest.mark.asyncio
async def test_unpause_before_pause_leaves_revision_tombstone() -> None:
    registry = PauseRegistry()
    run_id, pause_id = uuid4(), uuid4()
    assert await registry.apply(run_id, pause_id=pause_id, revision=2, requested=False)
    assert not await registry.apply(run_id, pause_id=pause_id, revision=1, requested=True)
    state = await registry.get(run_id)
    assert state is not None and not state.requested and state.revision == 2


@pytest.mark.asyncio
async def test_pause_revision_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        await PauseRegistry().apply(uuid4(), pause_id=uuid4(), revision=0, requested=True)


@pytest.mark.asyncio
async def test_pause_after_node_checkpoints_output_and_resumes(
    repo_contracts_root, workflow_linear_definition: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from ai_workflow.nodes.data.input import InputNodeExecutor
    from ai_workflow.runtime.engine.engine import (
        WorkflowRunCompleted,
        WorkflowRunError,
        WorkflowRunPaused,
        continue_workflow_from_checkpoint,
        run_workflow,
    )
    from ai_workflow.runtime.graph.keys import RuntimeKeys
    from ai_workflow.runtime.graph.scheduler import load_scheduler
    from ai_workflow.runtime.persistence.checkpoint import InMemoryCheckpointer
    from ai_workflow.runtime.registry.bootstrap import build_runner_registry

    run_id, pause_id = uuid4(), uuid4()
    pauses = PauseRegistry()
    checkpointer = InMemoryCheckpointer()
    original = InputNodeExecutor.execute
    calls = 0

    async def pause_after_input(self, context, config, inputs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        result = await original(self, context, config, inputs)
        await pauses.apply(run_id, pause_id=pause_id, revision=1, requested=True)
        return result

    monkeypatch.setattr(InputNodeExecutor, "execute", pause_after_input)
    registry = build_runner_registry(repo_contracts_root)
    outcome = await run_workflow(
        workflow_linear_definition,
        {"order_id": "ord-pause"},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        pause_registry=pauses,
    )
    assert isinstance(outcome, WorkflowRunPaused)
    saved = await checkpointer.load(thread_id=run_id)
    assert saved is not None
    scheduler = load_scheduler(saved)
    assert scheduler is not None and scheduler.pending
    assert scheduler.node_executions == 1

    pause = saved.runtime["_manual_pause"]
    assert isinstance(pause, dict)
    pause["paused_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    saved.runtime[RuntimeKeys.DEADLINE] = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    await checkpointer.save(thread_id=run_id, state=saved)

    with pytest.raises(WorkflowRunError, match="manually paused"):
        await continue_workflow_from_checkpoint(
            workflow_linear_definition,
            registry=registry,
            run_id=run_id,
            checkpointer=checkpointer,
            contracts_root=repo_contracts_root,
            pause_registry=pauses,
        )

    assert await pauses.apply(run_id, pause_id=pause_id, revision=2, requested=False)
    resumed = await continue_workflow_from_checkpoint(
        workflow_linear_definition,
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        pause_registry=pauses,
    )
    assert isinstance(resumed, WorkflowRunCompleted)
    assert resumed.output == {"order_id": "ord-pause"}
    assert calls == 1


@pytest.mark.asyncio
async def test_parallel_item_resumes_after_completed_body_node(
    repo_contracts_root, workflow_for_each_collect_definition: dict
) -> None:
    from copy import deepcopy

    from ai_workflow.contracts.workflow.definition import workflow_from_dict
    from ai_workflow.nodes.base import NodeResult
    from ai_workflow.runtime.control.foreach import ForEachFrame, run_foreach_frame
    from ai_workflow.runtime.graph.state import WorkflowState
    from ai_workflow.runtime.registry.bootstrap import build_runner_registry

    definition = deepcopy(workflow_for_each_collect_definition)
    first_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad03"
    second_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad06"
    second_node = deepcopy(definition["nodes"][2])
    second_node["id"] = second_id
    definition["nodes"].append(second_node)
    definition["edges"].append({
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbf04",
        "source_node_id": first_id,
        "source_port": "text",
        "target_node_id": second_id,
        "target_port": "variables",
    })
    workflow = workflow_from_dict(definition)
    registry = build_runner_registry(repo_contracts_root)
    pauses = PauseRegistry()
    run_id, pause_id = uuid4(), uuid4()
    calls: list[str] = []

    class Invoker:
        async def invoke(self, *, registration, context_factory, config, inputs, retry):
            del registration, config, inputs, retry
            context = context_factory(1)
            calls.append(str(context.node_id))
            if len(calls) == 1:
                await pauses.apply(run_id, pause_id=pause_id, revision=1, requested=True)
            return NodeResult(outputs={"text": {"value": "ok"}}), context

    async def is_paused() -> bool:
        state = await pauses.get(run_id)
        return state is not None and state.requested

    frame = ForEachFrame(
        for_each_node_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad02",
        collect_node_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad04",
        body_node_ids={first_id, second_id},
        body_entry_ids=[first_id],
        envelopes=[{"item_key": "item-1", "index": 0, "item": "alpha"}],
    )
    kwargs = {
        "workflow": workflow,
        "registry": registry,
        "state": WorkflowState(),
        "run_id": run_id,
        "workspace_id": uuid4(),
        "project_id": uuid4(),
        "credential_resolver": None,
        "invoker": Invoker(),
        "is_paused": is_paused,
    }
    frame = await run_foreach_frame(frame=frame, **kwargs)
    assert not frame.completed
    assert frame.item_positions["item-1"] == 1
    assert calls == [first_id]

    frame = ForEachFrame.from_json(frame.to_json())
    assert await pauses.apply(run_id, pause_id=pause_id, revision=2, requested=False)
    frame = await run_foreach_frame(frame=frame, **kwargs)
    assert frame.completed
    assert frame.item_status["item-1"] == "success"
    assert calls == [first_id, second_id]


@pytest.mark.asyncio
async def test_workflow_pause_preserves_pending_for_each_items(
    repo_contracts_root, workflow_for_each_collect_definition: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_workflow.nodes.ai.prompt_template import PromptTemplateNodeExecutor
    from ai_workflow.runtime.control.foreach import load_foreach_frames
    from ai_workflow.runtime.engine.engine import (
        WorkflowRunCompleted,
        WorkflowRunPaused,
        continue_workflow_from_checkpoint,
        run_workflow,
    )
    from ai_workflow.runtime.persistence.checkpoint import InMemoryCheckpointer
    from ai_workflow.runtime.registry.bootstrap import build_runner_registry

    run_id, pause_id = uuid4(), uuid4()
    pauses = PauseRegistry()
    checkpointer = InMemoryCheckpointer()
    original = PromptTemplateNodeExecutor.execute
    calls = 0

    async def pause_after_first(self, context, config, inputs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        result = await original(self, context, config, inputs)
        if calls == 1:
            await pauses.apply(run_id, pause_id=pause_id, revision=1, requested=True)
        return result

    monkeypatch.setattr(PromptTemplateNodeExecutor, "execute", pause_after_first)
    registry = build_runner_registry(repo_contracts_root)
    result = await run_workflow(
        workflow_for_each_collect_definition,
        {"items": ["alpha", "beta", "gamma"]},
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        pause_registry=pauses,
    )
    assert isinstance(result, WorkflowRunPaused)
    frame = load_foreach_frames(result.state)["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad02"]
    assert not frame.completed
    assert sum(status == "success" for status in frame.item_status.values()) == 1
    assert calls == 1

    await pauses.apply(run_id, pause_id=pause_id, revision=2, requested=False)
    resumed = await continue_workflow_from_checkpoint(
        workflow_for_each_collect_definition,
        registry=registry,
        run_id=run_id,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
        pause_registry=pauses,
    )
    assert isinstance(resumed, WorkflowRunCompleted)
    assert calls == 3
