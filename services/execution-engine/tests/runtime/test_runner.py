from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from uuid import UUID

import pytest

from ai_workflow.nodes.base import TransientNodeError
from ai_workflow.runtime.control.foreach import (
    COLLECT_INJECT_KEY,
    load_foreach_frames,
    save_foreach_frames,
)
from ai_workflow.runtime.engine.engine import (
    WorkflowRunCompleted,
    WorkflowRunError,
    continue_workflow_from_checkpoint,
    run_workflow,
)
from ai_workflow.runtime.graph.scheduler import load_scheduler, save_scheduler
from ai_workflow.runtime.persistence.checkpoint import InMemoryCheckpointer
from ai_workflow.runtime.registry.bootstrap import build_runner_registry


class RecordingHooks:
    def __init__(self) -> None:
        self.started: list[tuple[UUID, str]] = []
        self.completed: list[tuple[UUID, str]] = []
        self.failed: list[tuple[UUID, str, str]] = []

    async def on_node_started(self, *, node_id: UUID, node_type: str) -> None:
        self.started.append((node_id, node_type))

    async def on_node_completed(
        self,
        *,
        node_id: UUID,
        node_type: str,
        outputs: dict,
    ) -> None:
        self.completed.append((node_id, node_type))

    async def on_node_failed(self, *, node_id: UUID, node_type: str, error: str) -> None:
        self.failed.append((node_id, node_type, error))


@pytest.mark.asyncio
async def test_run_linear_workflow_pass_through(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_input = {"order_id": "ord-1", "priority": "high"}

    result = await run_workflow(
        workflow_linear_definition,
        run_input,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)

    assert result.output == run_input
    checkpoint = await checkpointer.load(thread_id=result.run_id)
    assert checkpoint is not None
    assert checkpoint.runtime["run_input"] == run_input


@pytest.mark.asyncio
async def test_run_linear_workflow_without_explicit_checkpointer(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)

    result = await run_workflow(
        workflow_linear_definition,
        {"order_id": "ord-2"},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)

    assert result.output == {"order_id": "ord-2"}


@pytest.mark.asyncio
async def test_run_field_bindings_workflow(
    repo_contracts_root: Path,
    workflow_field_bindings_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)

    result = await run_workflow(
        workflow_field_bindings_definition,
        {"order_id": "ord-1", "priority": "high"},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)
    assert result.output == {"order_id": "ord-1"}


@pytest.mark.asyncio
async def test_run_linear_workflow_invokes_hooks(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    hooks = RecordingHooks()

    await run_workflow(
        workflow_linear_definition,
        {"order_id": "ord-hooks"},
        registry=registry,
        hooks=hooks,
        contracts_root=repo_contracts_root,
    )

    assert len(hooks.started) == 2
    assert len(hooks.completed) == 2
    assert hooks.failed == []


@pytest.mark.asyncio
async def test_run_conditional_high_score_branch(
    repo_contracts_root: Path,
    workflow_conditional_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    result = await run_workflow(
        workflow_conditional_definition,
        {"score": 0.95},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)
    assert result.output == {"score": 0.95}
    true_output_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa03"
    false_output_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa04"
    assert true_output_id in result.state.node_outputs
    assert false_output_id not in result.state.node_outputs


@pytest.mark.asyncio
async def test_run_conditional_low_score_branch(
    repo_contracts_root: Path,
    workflow_conditional_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    result = await run_workflow(
        workflow_conditional_definition,
        {"score": 0.2},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)
    assert result.output == {"score": 0.2}
    false_output_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa04"
    assert false_output_id in result.state.node_outputs


@pytest.mark.asyncio
async def test_run_fan_out_fan_in(
    repo_contracts_root: Path,
    workflow_fan_out_fan_in_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    result = await run_workflow(
        workflow_fan_out_fan_in_definition,
        {"query": "markets"},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)
    assert result.output == {
        "summary": "Summarize: markets",
        "keywords": "Keywords: markets",
    }


@pytest.mark.asyncio
async def test_run_bounded_loop_exits_on_max_iterations(
    repo_contracts_root: Path,
    workflow_bounded_loop_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    result = await run_workflow(
        workflow_bounded_loop_definition,
        {"draft": "v1"},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)
    assert isinstance(result.output, dict)
    assert result.output.get("limit_reached") is True
    loop_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaac02"
    assert result.state.loop_iterations[loop_id] == 4


@pytest.mark.asyncio
async def test_run_rejects_arbitrary_cycle(repo_contracts_root: Path) -> None:
    path = repo_contracts_root / "fixtures" / "invalid" / "workflow-arbitrary-cycle.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    registry = build_runner_registry(repo_contracts_root)
    with pytest.raises(WorkflowRunError, match="ARBITRARY_CYCLE"):
        await run_workflow(raw, {}, registry=registry, contracts_root=repo_contracts_root)


@pytest.mark.asyncio
async def test_run_for_each_collect_workflow(
    repo_contracts_root: Path,
    workflow_for_each_collect_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    result = await run_workflow(
        workflow_for_each_collect_definition,
        {"items": ["alpha", "beta", "gamma"]},
        registry=registry,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(result, WorkflowRunCompleted)
    assert isinstance(result.output, dict)
    summary = result.output.get("summary")
    assert isinstance(summary, dict)
    assert summary["total"] == 3
    assert summary["completed"] == 3
    assert summary["failed"] == 0
    assert summary["skipped"] == 0
    successes = result.output.get("successes")
    assert isinstance(successes, list)
    assert len(successes) == 3


@pytest.mark.asyncio
async def test_run_for_each_rejects_over_cap(
    repo_contracts_root: Path,
    workflow_for_each_over_cap_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    with pytest.raises(WorkflowRunError, match="exceeds effective max_items"):
        await run_workflow(
            workflow_for_each_over_cap_definition,
            {"items": ["a", "b", "c"]},
            registry=registry,
            contracts_root=repo_contracts_root,
        )


@pytest.mark.asyncio
async def test_for_each_checkpoint_resume_skips_completed_items(
    repo_contracts_root: Path,
    workflow_for_each_collect_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("33333333-3333-4333-8333-333333333301")

    partial = await run_workflow(
        workflow_for_each_collect_definition,
        {"items": ["alpha", "beta"]},
        registry=registry,
        checkpointer=checkpointer,
        run_id=run_id,
        contracts_root=repo_contracts_root,
        max_fan_out_items=10,
    )
    assert isinstance(partial, WorkflowRunCompleted)

    frames = load_foreach_frames(partial.state)
    foreach_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad02"
    assert foreach_id in frames
    frame = frames[foreach_id]
    assert frame.completed is True
    assert all(status == "success" for status in frame.item_status.values())

    resumed = await continue_workflow_from_checkpoint(
        workflow_for_each_collect_definition,
        run_id=run_id,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(resumed, WorkflowRunCompleted)


FOREACH_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad02"
COLLECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad04"
OUTPUT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad05"


async def _rewind_foreach_checkpoint(
    checkpointer: InMemoryCheckpointer,
    run_id: UUID,
    *,
    drop_frame: bool,
    pending_last_item: bool,
) -> None:
    state = await checkpointer.load(thread_id=run_id)
    assert state is not None
    frames = load_foreach_frames(state)
    frame = frames[FOREACH_ID]
    if pending_last_item:
        last_key = str(frame.envelopes[-1]["item_key"])
        frame.item_status[last_key] = "pending"
        frame.item_results.pop(last_key, None)
        frame.item_errors.pop(last_key, None)
        frame.completion_seq.pop(last_key, None)
    frame.completed = False
    if drop_frame:
        frames.pop(FOREACH_ID)
    else:
        frames[FOREACH_ID] = frame
    save_foreach_frames(state, frames)
    state.runtime.pop(COLLECT_INJECT_KEY, None)
    state.node_outputs.pop(COLLECT_ID, None)
    state.node_outputs.pop(OUTPUT_ID, None)
    scheduler = load_scheduler(state)
    assert scheduler is not None
    scheduler.executed_output_ids.discard(OUTPUT_ID)
    scheduler.pending.clear()
    scheduler.in_pending.clear()
    scheduler.produced = {
        item for item in scheduler.produced if item[0] not in {COLLECT_ID, OUTPUT_ID}
    }
    for key in list(scheduler.production_order):
        if key[0] in {COLLECT_ID, OUTPUT_ID}:
            del scheduler.production_order[key]
    save_scheduler(state, scheduler)
    await checkpointer.save(thread_id=run_id, state=state)


@pytest.mark.asyncio
async def test_for_each_continue_resumes_incomplete_items(
    repo_contracts_root: Path,
    workflow_for_each_collect_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("33333333-3333-4333-8333-333333333302")

    completed = await run_workflow(
        workflow_for_each_collect_definition,
        {"items": ["alpha", "beta"]},
        registry=registry,
        checkpointer=checkpointer,
        run_id=run_id,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(completed, WorkflowRunCompleted)

    await _rewind_foreach_checkpoint(
        checkpointer, run_id, drop_frame=False, pending_last_item=True
    )

    resumed = await continue_workflow_from_checkpoint(
        workflow_for_each_collect_definition,
        run_id=run_id,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(resumed, WorkflowRunCompleted)
    frames = load_foreach_frames(resumed.state)
    assert frames[FOREACH_ID].completed is True
    assert all(status == "success" for status in frames[FOREACH_ID].item_status.values())
    summary = resumed.output.get("summary") if isinstance(resumed.output, dict) else None
    assert isinstance(summary, dict)
    assert summary["total"] == 2
    assert summary["completed"] == 2


@pytest.mark.asyncio
async def test_for_each_continue_rebuilds_missing_frame(
    repo_contracts_root: Path,
    workflow_for_each_collect_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    checkpointer = InMemoryCheckpointer()
    run_id = UUID("33333333-3333-4333-8333-333333333303")

    completed = await run_workflow(
        workflow_for_each_collect_definition,
        {"items": ["alpha", "beta"]},
        registry=registry,
        checkpointer=checkpointer,
        run_id=run_id,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(completed, WorkflowRunCompleted)

    await _rewind_foreach_checkpoint(
        checkpointer, run_id, drop_frame=True, pending_last_item=False
    )

    resumed = await continue_workflow_from_checkpoint(
        workflow_for_each_collect_definition,
        run_id=run_id,
        registry=registry,
        checkpointer=checkpointer,
        contracts_root=repo_contracts_root,
    )
    assert isinstance(resumed, WorkflowRunCompleted)
    summary = resumed.output.get("summary") if isinstance(resumed.output, dict) else None
    assert isinstance(summary, dict)
    assert summary["completed"] == 2


class _FlakyExecutor:
    """Wraps a delegate executor and raises TransientNodeError N times first."""

    node_type = "data.input@1"

    def __init__(self, delegate: object, *, fail_times: int) -> None:
        self._delegate = delegate
        self._fail_times = fail_times
        self.attempts = 0

    async def execute(self, context: object, config: object, inputs: object) -> object:
        self.attempts += 1
        if self.attempts <= self._fail_times:
            msg = f"synthetic transient failure #{self.attempts}"
            raise TransientNodeError(msg)
        return await self._delegate.execute(context, config, inputs)  # type: ignore[attr-defined]


def _zero_backoff(definition: dict) -> dict:
    patched = json.loads(json.dumps(definition))
    patched["execution_policy"]["default_retry"]["initial_backoff_ms"] = 0
    patched["execution_policy"]["default_retry"]["jitter"] = False
    return patched


@pytest.mark.asyncio
async def test_node_retries_transient_failure_then_succeeds(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    original = registry.get_node("data.input@1")
    flaky = _FlakyExecutor(original.executor_factory(), fail_times=2)
    registry._nodes["data.input@1"] = dataclasses.replace(  # noqa: SLF001 - test seam
        original,
        executor_factory=lambda: flaky,
    )

    run_input = {"order_id": "ord-1", "priority": "high"}
    result = await run_workflow(
        _zero_backoff(workflow_linear_definition),  # max_attempts=3
        run_input,
        registry=registry,
        checkpointer=InMemoryCheckpointer(),
        contracts_root=repo_contracts_root,
    )

    assert isinstance(result, WorkflowRunCompleted)
    assert result.output == run_input
    assert flaky.attempts == 3  # 2 transient failures + 1 success


@pytest.mark.asyncio
async def test_node_fails_when_transient_retries_exhausted(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    original = registry.get_node("data.input@1")
    flaky = _FlakyExecutor(original.executor_factory(), fail_times=99)
    registry._nodes["data.input@1"] = dataclasses.replace(  # noqa: SLF001 - test seam
        original,
        executor_factory=lambda: flaky,
    )

    with pytest.raises(WorkflowRunError, match="after 3 attempt"):
        await run_workflow(
            _zero_backoff(workflow_linear_definition),  # max_attempts=3
            {"order_id": "ord-1"},
            registry=registry,
            checkpointer=InMemoryCheckpointer(),
            contracts_root=repo_contracts_root,
        )
    assert flaky.attempts == 3

