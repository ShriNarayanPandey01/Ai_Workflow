from __future__ import annotations

from uuid import uuid4

import pytest

from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.nodes.control.collect import CollectNodeExecutor
from ai_workflow.nodes.control.condition import ConditionNodeExecutor
from ai_workflow.nodes.control.for_each import ForEachNodeExecutor
from ai_workflow.nodes.control.item_keys import stable_item_key
from ai_workflow.nodes.control.loop import LoopNodeExecutor
from ai_workflow.nodes.control.merge import MergeNodeExecutor


def _context(**runtime: object) -> ExecutionContext:
    return ExecutionContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=uuid4(),
        node_id=uuid4(),
        attempt=1,
        runtime=dict(runtime),
    )


@pytest.mark.asyncio
async def test_condition_routes_true_branch() -> None:
    executor = ConditionNodeExecutor()
    state_root = {
        "node_outputs": {
            "n1": {"value": {"score": 0.9}},
        }
    }
    result = await executor.execute(
        _context(_state_root=state_root),
        {
            "condition": {
                "op": "gte",
                "left": {"kind": "path", "value": "/node_outputs/n1/value/score"},
                "right": {"kind": "literal", "value": 0.8},
            }
        },
        {"value": {"score": 0.9}},
    )
    assert "true" in result.outputs
    assert "false" not in result.outputs


@pytest.mark.asyncio
async def test_merge_mappings_and_reject_conflict() -> None:
    executor = MergeNodeExecutor()
    result = await executor.execute(
        _context(),
        {
            "mappings": [
                {
                    "source_port": "branch_a",
                    "source_path": "/text",
                    "target_path": "/summary",
                },
                {
                    "source_port": "branch_b",
                    "source_path": "/text",
                    "target_path": "/keywords",
                },
            ],
            "on_conflict": "reject",
        },
        {
            "branch_a": {"text": "summary text"},
            "branch_b": {"text": "keyword text"},
        },
    )
    assert result.outputs["value"] == {
        "summary": "summary text",
        "keywords": "keyword text",
    }

    with pytest.raises(ValueError, match="conflict"):
        await executor.execute(
            _context(),
            {
                "mappings": [
                    {
                        "source_port": "branch_a",
                        "source_path": "/text",
                        "target_path": "/summary",
                    },
                    {
                        "source_port": "branch_b",
                        "source_path": "/text",
                        "target_path": "/summary",
                    },
                ],
                "on_conflict": "reject",
            },
            {
                "branch_a": {"text": "a"},
                "branch_b": {"text": "b"},
            },
        )


@pytest.mark.asyncio
async def test_loop_hits_max_iterations_then_done() -> None:
    executor = LoopNodeExecutor(platform_max_iterations=100)
    node_id = uuid4()
    runtime: dict = {"_loop_iterations": {}, "_state_root": {"node_outputs": {}}}
    context = ExecutionContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=uuid4(),
        node_id=node_id,
        attempt=1,
        runtime=runtime,
    )
    config = {"max_iterations": 2, "on_limit": "done"}

    first = await executor.execute(context, config, {"iteration": {"draft": "a"}})
    assert "body" in first.outputs

    second = await executor.execute(context, config, {"iteration": {"draft": "b"}})
    assert "body" in second.outputs

    third = await executor.execute(context, config, {"iteration": {"draft": "c"}})
    assert "done" in third.outputs
    assert third.outputs["done"]["limit_reached"] is True


@pytest.mark.asyncio
async def test_loop_on_limit_fail() -> None:
    executor = LoopNodeExecutor(platform_max_iterations=10)
    node_id = uuid4()
    context = ExecutionContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=uuid4(),
        node_id=node_id,
        attempt=1,
        runtime={"_loop_iterations": {str(node_id): 1}, "_state_root": {}},
    )
    with pytest.raises(ValueError, match="exceeded max_iterations"):
        await executor.execute(
            context,
            {"max_iterations": 1, "on_limit": "fail"},
            {"iteration": {}},
        )


@pytest.mark.asyncio
async def test_for_each_builds_stable_item_keys() -> None:
    executor = ForEachNodeExecutor(platform_max_fan_out_items=100)
    context = _context(_max_fan_out_items=100)
    config = {
        "max_items": 10,
        "concurrency": 2,
        "item_timeout_seconds": 30,
        "ordering": "preserve_input",
        "failure_policy": "continue",
    }
    result = await executor.execute(
        context,
        config,
        {"items": {"items": ["alpha", "beta"]}},
    )
    envelopes = result.outputs["item"]
    assert isinstance(envelopes, list)
    assert len(envelopes) == 2
    assert envelopes[0]["item_key"] == stable_item_key(0, "alpha")
    assert envelopes[1]["item_key"] == stable_item_key(1, "beta")
    assert result.outputs["done"] == {"count": 2}


@pytest.mark.asyncio
async def test_for_each_rejects_over_cap() -> None:
    executor = ForEachNodeExecutor(platform_max_fan_out_items=2)
    context = _context(_max_fan_out_items=2)
    config = {
        "max_items": 10,
        "concurrency": 1,
        "item_timeout_seconds": 30,
        "ordering": "preserve_input",
        "failure_policy": "continue",
    }
    with pytest.raises(ValueError, match="exceeds effective max_items"):
        await executor.execute(
            context,
            config,
            {"items": {"items": ["a", "b", "c"]}},
        )


@pytest.mark.asyncio
async def test_collect_summarizes_items() -> None:
    executor = CollectNodeExecutor()
    result = await executor.execute(
        _context(),
        {"ordering": "preserve_input", "artifact_threshold_bytes": 1_048_576},
        {
            "items": [
                {
                    "item_key": "0:abc",
                    "index": 0,
                    "status": "success",
                    "value": {"text": "one"},
                },
                {
                    "item_key": "1:def",
                    "index": 1,
                    "status": "failure",
                    "error": "boom",
                },
                {
                    "item_key": "2:ghi",
                    "index": 2,
                    "status": "skipped",
                },
            ]
        },
    )
    payload = result.outputs["result"]
    assert isinstance(payload, dict)
    assert payload["summary"] == {
        "total": 3,
        "completed": 1,
        "failed": 1,
        "skipped": 1,
    }
    assert len(payload["successes"]) == 1
    assert len(payload["failures"]) == 1
    assert len(payload["skipped"]) == 1


@pytest.mark.asyncio
async def test_collect_overflow_strips_bulk_arrays() -> None:
    from ai_workflow.runtime.artifact_store import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    executor = CollectNodeExecutor(artifact_store=store)
    result = await executor.execute(
        _context(),
        {"ordering": "preserve_input", "artifact_threshold_bytes": 10},
        {
            "items": [
                {
                    "item_key": "0:abc",
                    "index": 0,
                    "status": "success",
                    "value": {"text": "one-long-enough-to-overflow"},
                }
            ]
        },
    )
    payload = result.outputs["result"]
    assert payload["successes"] == []
    assert payload["failures"] == []
    assert payload["skipped"] == []
    assert isinstance(payload["artifact_ref"], str)
    stored = store.get(str(payload["artifact_ref"]))
    assert isinstance(stored, dict)
    assert stored["successes"]

