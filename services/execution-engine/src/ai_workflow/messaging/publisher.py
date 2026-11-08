from __future__ import annotations

import json
from uuid import UUID, uuid4

import aio_pika
import asyncpg

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.messaging.broker import MessagingNames
from ai_workflow.messaging.envelope import (
    ExecutionSubject,
    MessageEnvelope,
    utc_now_iso,
)
from ai_workflow.security.redaction import redact_value


class EventPublisher:
    """Publishes sequenced execution and node lifecycle events to RabbitMQ."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        channel: aio_pika.abc.AbstractChannel,
        source_envelope: MessageEnvelope,
        subject: ExecutionSubject,
    ) -> None:
        self._pool = pool
        self._channel = channel
        self._source = source_envelope
        self._subject = subject
        self._names = MessagingNames
        self._subject_dict = {
            "workflow_id": str(subject.workflow_id),
            "workflow_version_id": (
                str(subject.workflow_version_id) if subject.workflow_version_id else None
            ),
            "run_id": str(subject.run_id),
            "node_id": None,
            "task_id": None,
            "document_id": None,
        }

    async def get_last_sequence(self) -> int:
        """Return the highest event sequence already emitted for this run."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_sequence FROM ee.run_sequences WHERE run_id = $1",
                self._subject.run_id,
            )
        if row is None:
            return 0
        return int(row["last_sequence"])

    async def allocate_sequence(self) -> int:
        """Atomically reserve the next monotonic sequence number for this run."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO ee.run_sequences (run_id, last_sequence)
                    VALUES ($1, 1)
                    ON CONFLICT (run_id) DO UPDATE
                    SET last_sequence = ee.run_sequences.last_sequence + 1
                    RETURNING last_sequence
                    """,
                    self._subject.run_id,
                )
        assert row is not None
        return int(row["last_sequence"])

    async def publish(
        self,
        *,
        message_type: str,
        routing_key: str,
        payload: dict[str, JsonValue],
        idempotency_suffix: str,
    ) -> int:
        """Build, redact, and publish a contract envelope to the events exchange."""
        sequence = await self.allocate_sequence()
        envelope = MessageEnvelope.event_dict(
            message_id=uuid4(),
            message_type=message_type,
            correlation_id=self._source.correlation_id,
            causation_id=self._source.message_id,
            idempotency_key=f"{idempotency_suffix}:{self._subject.run_id}:{sequence}",
            tenant=self._source.tenant,
            subject=self._subject_dict,
            sequence=sequence,
            payload=redact_value(payload),
        )
        exchange = await self._channel.get_exchange(self._names.EVENTS_EXCHANGE)
        body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        await exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
        return sequence

    async def publish_execution_started(self) -> int:
        return await self.publish(
            message_type="execution.started",
            routing_key=self._names.EXECUTION_STARTED_ROUTING_KEY,
            payload={"status": "RUNNING", "started_at": utc_now_iso()},
            idempotency_suffix="execution.started",
        )

    async def publish_execution_completed(self, *, outputs: JsonValue) -> int:
        return await self.publish(
            message_type="execution.completed",
            routing_key=self._names.EXECUTION_COMPLETED_ROUTING_KEY,
            payload={
                "status": "SUCCEEDED",
                "outputs": outputs if isinstance(outputs, dict) else {"value": outputs},
                "finished_at": utc_now_iso(),
            },
            idempotency_suffix="execution.completed",
        )

    async def publish_execution_failed(
        self,
        *,
        code: str,
        message: str,
        status: str = "FAILED",
    ) -> int:
        event_status = status if status in {"FAILED", "TIMED_OUT"} else "FAILED"
        return await self.publish(
            message_type="execution.failed",
            routing_key=self._names.EXECUTION_FAILED_ROUTING_KEY,
            payload={
                "status": event_status,
                "error": {"code": code, "message": message, "retryable": False},
                "finished_at": utc_now_iso(),
            },
            idempotency_suffix="execution.failed",
        )

    async def publish_execution_waiting(
        self,
        *,
        waiting_reason: str,
        interrupt_id: UUID,
        node_id: UUID | None = None,
        approval_request: dict[str, JsonValue] | None = None,
        approval_id: UUID | None = None,
    ) -> int:
        payload: dict[str, JsonValue] = {
            "status": "WAITING",
            "waiting_reason": waiting_reason,
            "interrupt_id": str(interrupt_id),
        }
        if node_id is not None:
            payload["node_id"] = str(node_id)
        if approval_id is not None:
            payload["approval_id"] = str(approval_id)
        if approval_request is not None:
            payload["approval_request"] = approval_request
        else:
            payload["approval_request"] = None
        return await self.publish(
            message_type="execution.waiting",
            routing_key=self._names.EXECUTION_WAITING_ROUTING_KEY,
            payload=payload,
            idempotency_suffix="execution.waiting",
        )

    async def publish_execution_cancelled(self, *, reason: str) -> int:
        return await self.publish(
            message_type="execution.cancelled",
            routing_key=self._names.EXECUTION_CANCELLED_ROUTING_KEY,
            payload={
                "status": "CANCELLED",
                "reason": reason,
                "finished_at": utc_now_iso(),
            },
            idempotency_suffix="execution.cancelled",
        )

    async def publish_node_started(self, *, node_id: UUID, node_type: str, attempt: int = 1) -> int:
        return await self.publish(
            message_type="node.started",
            routing_key=self._names.NODE_STARTED_ROUTING_KEY,
            payload={
                "node_id": str(node_id),
                "node_type": node_type,
                "attempt": attempt,
                "status": "RUNNING",
                "started_at": utc_now_iso(),
            },
            idempotency_suffix=f"node.started:{node_id}",
        )

    async def publish_node_completed(
        self,
        *,
        node_id: UUID,
        node_type: str,
        outputs: dict[str, JsonValue],
        attempt: int = 1,
    ) -> int:
        return await self.publish(
            message_type="node.completed",
            routing_key=self._names.NODE_COMPLETED_ROUTING_KEY,
            payload={
                "node_id": str(node_id),
                "node_type": node_type,
                "attempt": attempt,
                "status": "SUCCEEDED",
                "outputs": outputs,
                "finished_at": utc_now_iso(),
            },
            idempotency_suffix=f"node.completed:{node_id}",
        )

    async def publish_node_failed(
        self,
        *,
        node_id: UUID,
        node_type: str,
        message: str,
        attempt: int = 1,
    ) -> int:
        return await self.publish(
            message_type="node.failed",
            routing_key=self._names.NODE_FAILED_ROUTING_KEY,
            payload={
                "node_id": str(node_id),
                "node_type": node_type,
                "attempt": attempt,
                "status": "FAILED",
                "error": {"code": "NODE_EXECUTION_FAILED", "message": message, "retryable": False},
                "finished_at": utc_now_iso(),
            },
            idempotency_suffix=f"node.failed:{node_id}",
        )


class PublisherHooks:
    """Adapt an EventPublisher to the WorkflowRunHooks callback interface."""

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    async def on_node_started(self, *, node_id: UUID, node_type: str) -> None:
        await self._publisher.publish_node_started(node_id=node_id, node_type=node_type)

    async def on_node_completed(
        self,
        *,
        node_id: UUID,
        node_type: str,
        outputs: dict[str, JsonValue],
    ) -> None:
        await self._publisher.publish_node_completed(
            node_id=node_id,
            node_type=node_type,
            outputs=outputs,
        )

    async def on_node_failed(self, *, node_id: UUID, node_type: str, error: str) -> None:
        await self._publisher.publish_node_failed(
            node_id=node_id, node_type=node_type, message=error
        )
