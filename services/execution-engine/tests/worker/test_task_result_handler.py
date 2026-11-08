from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from ai_workflow.config.settings import Settings
from ai_workflow.messaging.inbox import ClaimResult
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.graph.scheduler import get_interrupt, save_interrupt
from ai_workflow.runtime.graph.state import WorkflowState
from ai_workflow.worker.handler import ExecutionCommandHandler, MessageNotReadyError


def _task_completed_body() -> bytes:
    envelope = {
        "message_id": "33333333-3333-4333-8333-333333333309",
        "message_type": "task.completed",
        "schema_version": "1.0",
        "occurred_at": "2026-07-24T12:55:00Z",
        "correlation_id": "44444444-4444-4444-8444-444444444401",
        "causation_id": "33333333-3333-4333-8333-333333333301",
        "idempotency_key": "task.completed:99999999-9999-4999-8999-999999999901",
        "tenant": {
            "workspace_id": "55555555-5555-4555-8555-555555555501",
            "project_id": "66666666-6666-4666-8666-666666666601",
        },
        "subject": {
            "workflow_id": "11111111-1111-4111-8111-111111111101",
            "workflow_version_id": "22222222-2222-4222-8222-222222222201",
            "run_id": "44444444-4444-4444-8444-444444444401",
            "node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
            "task_id": "99999999-9999-4999-8999-999999999901",
        },
        "sequence": 1,
        "payload": {
            "task_id": "99999999-9999-4999-8999-999999999901",
            "status": "SUCCEEDED",
            "result": {"report": {"executive_summary": "done"}},
        },
    }
    return json.dumps(envelope).encode("utf-8")


def _task_failed_body() -> bytes:
    envelope = {
        "message_id": "33333333-3333-4333-8333-333333333310",
        "message_type": "task.failed",
        "schema_version": "1.0",
        "occurred_at": "2026-07-24T12:55:00Z",
        "correlation_id": "44444444-4444-4444-8444-444444444401",
        "causation_id": "33333333-3333-4333-8333-333333333301",
        "idempotency_key": "task.failed:99999999-9999-4999-8999-999999999901",
        "tenant": {
            "workspace_id": "55555555-5555-4555-8555-555555555501",
            "project_id": "66666666-6666-4666-8666-666666666601",
        },
        "subject": {
            "workflow_id": "11111111-1111-4111-8111-111111111101",
            "workflow_version_id": "22222222-2222-4222-8222-222222222201",
            "run_id": "44444444-4444-4444-8444-444444444401",
            "node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
            "task_id": "99999999-9999-4999-8999-999999999901",
        },
        "sequence": 1,
        "payload": {
            "task_id": "99999999-9999-4999-8999-999999999901",
            "status": "FAILED",
            "error": {"code": "TASK_FAILED", "message": "research timed out"},
        },
    }
    return json.dumps(envelope).encode("utf-8")


def _task_completed_body() -> bytes:
    envelope = {
        "message_id": "33333333-3333-4333-8333-333333333309",
        "message_type": "task.completed",
        "schema_version": "1.0",
        "occurred_at": "2026-07-24T12:55:00Z",
        "correlation_id": "44444444-4444-4444-8444-444444444401",
        "causation_id": "33333333-3333-4333-8333-333333333301",
        "idempotency_key": "task.completed:99999999-9999-4999-8999-999999999901",
        "tenant": {
            "workspace_id": "55555555-5555-4555-8555-555555555501",
            "project_id": "66666666-6666-4666-8666-666666666601",
        },
        "subject": {
            "workflow_id": "11111111-1111-4111-8111-111111111101",
            "workflow_version_id": "22222222-2222-4222-8222-222222222201",
            "run_id": "44444444-4444-4444-8444-444444444401",
            "node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
            "task_id": "99999999-9999-4999-8999-999999999901",
        },
        "sequence": 1,
        "payload": {
            "task_id": "99999999-9999-4999-8999-999999999901",
            "status": "SUCCEEDED",
            "result": {"report": {"executive_summary": "done"}},
        },
    }
    return json.dumps(envelope).encode("utf-8")


@pytest.fixture
def handler_settings(repo_contracts_root) -> Settings:
    return Settings(
        AIW_DATABASE_URL="postgresql://aiw:aiw@localhost:5432/aiw",
        AIW_RABBITMQ_URL="amqp://aiw:aiw@localhost:5672/",
        AIW_SERVICE_ROLE="execution-worker",
        AIW_CONTRACTS_ROOT=repo_contracts_root,
    )


@pytest.mark.asyncio
async def test_task_completed_without_interrupt_is_retried(
    handler_settings: Settings,
) -> None:
    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=MagicMock(),
        channel=MagicMock(),
        registry=MagicMock(),
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.NEW)
    handler._inbox.mark_failed = AsyncMock()

    with (
        patch(
            "ai_workflow.worker.handler.PostgresCheckpointer.load",
            new=AsyncMock(return_value=None),
        ),
        patch("ai_workflow.worker.handler.asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(MessageNotReadyError):
            await handler.handle(_task_completed_body())

    handler._inbox.mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_failed_clears_interrupt_before_publish(
    handler_settings: Settings,
) -> None:
    waiting = WorkflowState()
    save_interrupt(
        waiting,
        interrupt_id="77777777-7777-4777-8777-777777777701",
        waiting_reason="TASK",
        node_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        approval_id=None,
        node_type="research.deep-research@1",
        approval_request={"task_type": "research.deep-research@1"},
        task_id="99999999-9999-4999-8999-999999999901",
    )
    assert get_interrupt(waiting) is not None

    handler = ExecutionCommandHandler(
        settings=handler_settings,
        pool=MagicMock(),
        channel=MagicMock(),
        registry=MagicMock(),
        cancel_registry=CancelRegistry(),
    )
    handler._inbox = MagicMock()
    handler._inbox.claim = AsyncMock(return_value=ClaimResult.NEW)
    handler._inbox.mark_failed = AsyncMock()

    checkpointer = MagicMock()
    checkpointer.load = AsyncMock(return_value=waiting)
    checkpointer.save = AsyncMock()
    publisher = MagicMock()
    publisher.publish_execution_failed = AsyncMock()

    with (
        patch("ai_workflow.worker.handler.PostgresCheckpointer", return_value=checkpointer),
        patch("ai_workflow.worker.handler.EventPublisher", return_value=publisher),
    ):
        await handler.handle(_task_failed_body())

    checkpointer.save.assert_awaited_once()
    saved_state = checkpointer.save.await_args.kwargs["state"]
    assert get_interrupt(saved_state) is None
    publisher.publish_execution_failed.assert_awaited_once()
    handler._inbox.mark_failed.assert_awaited_once()
    assert checkpointer.save.await_args.kwargs["thread_id"] == UUID(
        "44444444-4444-4444-8444-444444444401"
    )
