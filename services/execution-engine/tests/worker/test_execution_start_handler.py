from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_workflow.config.settings import Settings
from ai_workflow.messaging.inbox import ClaimResult
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.worker.handler import ExecutionCommandHandler, MessageInFlightError


@pytest.fixture
def execution_start_body(repo_contracts_root: Path) -> bytes:
    fixture_path = (
        repo_contracts_root / "fixtures" / "valid" / "envelope-execution-start.json"
    )
    return fixture_path.read_bytes()


@pytest.fixture
def handler_settings(repo_contracts_root: Path) -> Settings:
    return Settings(
        AIW_DATABASE_URL="postgresql://aiw:aiw@localhost:5432/aiw",
        AIW_RABBITMQ_URL="amqp://aiw:aiw@localhost:5672/",
        AIW_SERVICE_ROLE="execution-worker",
        AIW_CONTRACTS_ROOT=repo_contracts_root,
    )


@pytest.mark.asyncio
async def test_handler_skips_duplicate_completed(
    handler_settings: Settings,
    execution_start_body: bytes,
) -> None:
    pool = MagicMock()
    channel = MagicMock()
    registry = MagicMock()

    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=pool,
        channel=channel,
        registry=registry,
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.DUPLICATE_COMPLETED)

    await handler.handle(execution_start_body)

    handler._inbox.claim.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_raises_when_message_in_flight(
    handler_settings: Settings,
    execution_start_body: bytes,
) -> None:
    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=MagicMock(),
        channel=MagicMock(),
        registry=MagicMock(),
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.DUPLICATE_IN_FLIGHT)

    with pytest.raises(MessageInFlightError):
        await handler.handle(execution_start_body)


@pytest.mark.asyncio
async def test_handler_runs_workflow_for_new_claim(
    handler_settings: Settings,
    execution_start_body: bytes,
    repo_contracts_root: Path,
) -> None:
    from ai_workflow.runtime.registry.bootstrap import build_runner_registry

    pool = MagicMock()
    channel = MagicMock()
    registry = build_runner_registry(repo_contracts_root)

    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=pool,
        channel=channel,
        registry=registry,
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.NEW)
    handler._inbox.mark_completed = AsyncMock()

    publisher = MagicMock()
    publisher.get_last_sequence = AsyncMock(return_value=0)
    publisher.publish_execution_started = AsyncMock(return_value=1)
    publisher.publish_execution_completed = AsyncMock(return_value=2)
    publisher.publish_node_started = AsyncMock(return_value=3)
    publisher.publish_node_completed = AsyncMock(return_value=4)

    handler._pool = pool
    checkpointer = MagicMock()
    checkpointer.save = AsyncMock()
    checkpointer.load = AsyncMock(return_value=None)

    import ai_workflow.worker.handler as handler_module

    original_postgres = handler_module.PostgresCheckpointer
    original_publisher = handler_module.EventPublisher
    original_hooks = handler_module.PublisherHooks
    handler_module.PostgresCheckpointer = MagicMock(return_value=checkpointer)
    handler_module.EventPublisher = MagicMock(return_value=publisher)
    hooks = MagicMock()
    hooks.on_node_started = AsyncMock()
    hooks.on_node_completed = AsyncMock()
    hooks.on_node_failed = AsyncMock()
    handler_module.PublisherHooks = MagicMock(return_value=hooks)

    try:
        await handler.handle(execution_start_body)
    finally:
        handler_module.PostgresCheckpointer = original_postgres
        handler_module.EventPublisher = original_publisher
        handler_module.PublisherHooks = original_hooks

    handler._inbox.mark_completed.assert_awaited_once()
    publisher.publish_execution_started.assert_awaited_once()
    publisher.publish_execution_completed.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_ignores_start_while_waiting(
    handler_settings: Settings,
    execution_start_body: bytes,
) -> None:
    from ai_workflow.runtime.graph.state import WorkflowState

    waiting = WorkflowState()
    waiting.runtime["_interrupt"] = {
        "interrupt_id": "77777777-7777-4777-8777-777777777701",
        "waiting_reason": "HUMAN",
        "node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaab02",
        "approval_id": "88888888-8888-4888-8888-888888888801",
        "node_type": "human.approval@1",
        "approval_request": {},
    }

    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=MagicMock(),
        channel=MagicMock(),
        registry=MagicMock(),
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.NEW)
    handler._inbox.mark_completed = AsyncMock()

    publisher = MagicMock()
    publisher.get_last_sequence = AsyncMock(return_value=1)
    publisher.publish_execution_failed = AsyncMock()

    checkpointer = MagicMock()
    checkpointer.load = AsyncMock(return_value=waiting)

    import ai_workflow.worker.handler as handler_module

    original_postgres = handler_module.PostgresCheckpointer
    original_publisher = handler_module.EventPublisher
    handler_module.PostgresCheckpointer = MagicMock(return_value=checkpointer)
    handler_module.EventPublisher = MagicMock(return_value=publisher)
    try:
        await handler.handle(execution_start_body)
    finally:
        handler_module.PostgresCheckpointer = original_postgres
        handler_module.EventPublisher = original_publisher

    handler._inbox.mark_completed.assert_awaited_once()
    publisher.publish_execution_failed.assert_not_called()


@pytest.mark.asyncio
async def test_handler_cancel_waiting_publishes_cancelled(
    handler_settings: Settings,
    repo_contracts_root: Path,
) -> None:
    from ai_workflow.runtime.graph.state import WorkflowState

    cancel_body = (
        repo_contracts_root / "fixtures" / "valid" / "envelope-execution-cancel.json"
    ).read_bytes()
    waiting = WorkflowState()
    waiting.runtime["_interrupt"] = {
        "interrupt_id": "77777777-7777-4777-8777-777777777701",
        "waiting_reason": "HUMAN",
        "node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaab02",
        "approval_id": "88888888-8888-4888-8888-888888888801",
        "node_type": "human.approval@1",
        "approval_request": {},
    }

    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=MagicMock(),
        channel=MagicMock(),
        registry=MagicMock(),
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.NEW)
    handler._inbox.mark_completed = AsyncMock()

    publisher = MagicMock()
    publisher.publish_execution_cancelled = AsyncMock()
    checkpointer = MagicMock()
    checkpointer.load = AsyncMock(return_value=waiting)
    checkpointer.save = AsyncMock()

    import ai_workflow.worker.handler as handler_module

    original_postgres = handler_module.PostgresCheckpointer
    original_publisher = handler_module.EventPublisher
    handler_module.PostgresCheckpointer = MagicMock(return_value=checkpointer)
    handler_module.EventPublisher = MagicMock(return_value=publisher)
    try:
        await handler.handle(cancel_body)
    finally:
        handler_module.PostgresCheckpointer = original_postgres
        handler_module.EventPublisher = original_publisher

    publisher.publish_execution_cancelled.assert_awaited_once()
    checkpointer.save.assert_awaited_once()
    handler._inbox.mark_completed.assert_awaited_once()
    assert "_interrupt" not in waiting.runtime
