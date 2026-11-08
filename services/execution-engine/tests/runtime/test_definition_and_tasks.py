from __future__ import annotations

from uuid import uuid4

import pytest

from ai_workflow.runtime.engine.engine import _parse_definition
from ai_workflow.runtime.graph.ir import get_workflow_ir
from ai_workflow.runtime.persistence.definition_store import (
    InMemoryDefinitionStore,
    hash_definition,
)
from ai_workflow.tasks.base import TaskContext
from ai_workflow.tasks.research import DeepResearchTaskExecutor


def test_hash_definition_is_stable() -> None:
    document = {"nodes": [], "name": "wf"}
    assert hash_definition(document) == hash_definition(dict(document))


def test_ir_hash_differs_from_raw_fixture_document(repo_contracts_root) -> None:
    import json

    raw = json.loads(
        (repo_contracts_root / "fixtures" / "valid" / "workflow-e2e-full-features.json").read_text(
            encoding="utf-8"
        )
    )
    workflow = _parse_definition(raw, contracts_root=repo_contracts_root)
    ir = get_workflow_ir(workflow)
    canonical = workflow.model_dump(mode="json", exclude_none=True)
    assert hash_definition(canonical) == ir.definition_hash
    assert hash_definition(raw) != ir.definition_hash


@pytest.mark.asyncio
async def test_in_memory_definition_store_round_trip() -> None:
    store = InMemoryDefinitionStore()
    document = {"workflow_id": "abc", "nodes": []}
    digest = await store.put(document)
    loaded = await store.get(digest)
    assert loaded == document


@pytest.mark.asyncio
async def test_deep_research_task_skips_completed_item() -> None:
    executor = DeepResearchTaskExecutor()
    context = TaskContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=None,
        node_id=uuid4(),
        task_id=uuid4(),
        attempt=1,
    )
    from ai_workflow.tasks.base import TaskCheckpoint

    result = await executor.run(
        context,
        {"request": {"question": "What is X?", "seed_sources": []}},
        TaskCheckpoint(data={"completed_items": ["report"]}),
    )
    assert "report" in result.outputs
    assert result.metadata["completed_items"] == ["report"]
