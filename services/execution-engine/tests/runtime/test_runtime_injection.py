from __future__ import annotations

from pathlib import Path

import pytest
from ai_workflow.runtime.bootstrap import build_runner_registry
from ai_workflow.runtime.engine.engine import WorkflowEngine
from ai_workflow.runtime.engine.invoke import NodeInvoker, RetryingNodeInvoker
from ai_workflow.runtime.semantics.validator import CatalogSemanticValidator, SemanticValidator


class RecordingInvoker(NodeInvoker):
    def __init__(self, inner: NodeInvoker) -> None:
        self.inner = inner
        self.calls = 0

    async def invoke(self, **kwargs):
        self.calls += 1
        return await self.inner.invoke(**kwargs)


class RecordingSemantic(SemanticValidator):
    def __init__(self, inner: CatalogSemanticValidator) -> None:
        self.inner = inner
        self.validated = 0

    def validate(self, definition) -> None:
        self.validated += 1
        self.inner.validate(definition)

    def build_state_root(self, **kwargs):
        return self.inner.build_state_root(**kwargs)


@pytest.mark.asyncio
async def test_workflow_engine_uses_injected_invoker_and_semantic(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    registry = build_runner_registry(repo_contracts_root)
    invoker = RecordingInvoker(RetryingNodeInvoker())
    semantic = RecordingSemantic(
        CatalogSemanticValidator(contracts_root=repo_contracts_root)
    )
    engine = WorkflowEngine(registry=registry, node_invoker=invoker, semantic=semantic)
    await engine.run(
        workflow_linear_definition,
        {"order_id": "ord-1", "priority": "high"},
        contracts_root=repo_contracts_root,
    )
    assert semantic.validated == 1
    assert invoker.calls >= 1
