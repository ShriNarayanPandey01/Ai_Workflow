from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workflow.contracts.nodes.catalog_loader import reset_manifest_schema_cache
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.registry import (
    DuplicateRegistrationError,
    MissingExecutorError,
    OrphanExecutorError,
    RuntimeRegistry,
    WrongExecutorKindError,
)
from ai_workflow.tasks.base import TaskCheckpoint, TaskContext, TaskResult


class _FakeInputExecutor:
    node_type = "data.input@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict,
        inputs: dict,
    ) -> NodeResult:
        return NodeResult(outputs={"value": inputs})


class _FakeOutputExecutor:
    node_type = "data.output@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict,
        inputs: dict,
    ) -> NodeResult:
        return NodeResult()


class _FakeChatExecutor:
    node_type = "ai.chat-model@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict,
        inputs: dict,
    ) -> NodeResult:
        return NodeResult(outputs={"response": {"text": "ok"}})


class _FakeResearchTask:
    task_type = "research.deep-research@1"

    async def run(
        self,
        context: TaskContext,
        payload: dict,
        checkpoint: TaskCheckpoint | None,
    ) -> TaskResult:
        return TaskResult(outputs={"report": {"executive_summary": "done"}})


@pytest.fixture(autouse=True)
def _reset_schema_cache() -> Iterator[None]:
    reset_manifest_schema_cache()
    yield
    reset_manifest_schema_cache()


def _registry(contracts_root: Path, catalog_dir: Path) -> RuntimeRegistry:
    return RuntimeRegistry(contracts_root=contracts_root)


def test_build_registers_inline_and_durable_executors(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_node(lambda: _FakeInputExecutor(), node_type="data.input@1")
    registry.register_node(lambda: _FakeOutputExecutor(), node_type="data.output@1")
    registry.register_node(lambda: _FakeChatExecutor(), node_type="ai.chat-model@1")
    registry.register_task(
        lambda: _FakeResearchTask(),
        task_type="research.deep-research@1",
    )

    built = registry.build(strict_catalog=True, catalog_dir=mini_catalog_dir)

    assert "data.input@1" in built.nodes
    assert "ai.chat-model@1" in built.nodes
    assert "research.deep-research@1" in built.tasks


def test_duplicate_registration_fails(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_node(lambda: _FakeInputExecutor(), node_type="data.input@1")

    with pytest.raises(DuplicateRegistrationError):
        registry.register_node(lambda: _FakeInputExecutor(), node_type="data.input@1")


def test_orphan_executor_fails(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_node(lambda: _FakeInputExecutor(), node_type="unknown.node@1")

    with pytest.raises(OrphanExecutorError):
        registry.build(catalog_dir=mini_catalog_dir)


def test_missing_executor_fails_in_strict_mode(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_node(lambda: _FakeInputExecutor(), node_type="data.input@1")

    with pytest.raises(MissingExecutorError):
        registry.build(strict_catalog=True, catalog_dir=mini_catalog_dir)


def test_wrong_executor_kind_inline_for_durable_task(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_node(
        lambda: _FakeInputExecutor(),
        node_type="research.deep-research@1",
    )

    with pytest.raises(WrongExecutorKindError):
        registry.build(catalog_dir=mini_catalog_dir)


def test_wrong_executor_kind_durable_for_inline_node(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_task(lambda: _FakeResearchTask(), task_type="data.input@1")

    with pytest.raises(WrongExecutorKindError):
        registry.build(catalog_dir=mini_catalog_dir)


def test_default_bindings_indexed_on_registration(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    registry = _registry(repo_contracts_root, mini_catalog_dir)
    registry.register_node(lambda: _FakeChatExecutor(), node_type="ai.chat-model@1")

    built = registry.build(catalog_dir=mini_catalog_dir)
    entry = built.nodes["ai.chat-model@1"]

    assert "prompt" in entry.default_bindings_by_port
    assert entry.default_bindings_by_port["prompt"][0].target_path == "/text"


def test_non_strict_build_without_executors(
    repo_contracts_root: Path,
) -> None:
    registry = RuntimeRegistry(contracts_root=repo_contracts_root)
    built = registry.build(strict_catalog=False)

    assert len(built.catalog) == 18
    assert not built.nodes
    assert not built.tasks


def test_executor_context_types_are_usable() -> None:
    context = ExecutionContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=uuid4(),
        node_id=uuid4(),
        attempt=1,
    )
    assert context.attempt == 1

    task_context = TaskContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=None,
        node_id=uuid4(),
        task_id=uuid4(),
        attempt=1,
    )
    assert task_context.workflow_version_id is None
