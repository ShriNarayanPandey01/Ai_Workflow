from __future__ import annotations

import json
from uuid import UUID, uuid4

import aio_pika

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.messaging.broker import MessagingNames
from ai_workflow.messaging.envelope import ExecutionSubject, MessageEnvelope


class RabbitTaskDispatcher:
    """Publishes task.start commands for durable-task nodes."""

    def __init__(
        self,
        *,
        channel: aio_pika.abc.AbstractChannel,
        source_envelope: MessageEnvelope,
        subject: ExecutionSubject,
    ) -> None:
        self._channel = channel
        self._source = source_envelope
        self._subject = subject

    async def start_task(
        self,
        *,
        run_id: UUID,
        node_id: UUID,
        task_type: str,
        payload: dict[str, JsonValue],
        credential_refs: dict[str, UUID],
        resource_refs: dict[str, UUID],
        budgets: dict[str, JsonValue],
        task_id: UUID | None = None,
    ) -> UUID:
        if task_id is None:
            task_id = uuid4()
        subject = self._subject.model_dump(mode="json")
        subject["run_id"] = str(run_id)
        subject["node_id"] = str(node_id)
        subject["task_id"] = str(task_id)
        envelope = MessageEnvelope.event_dict(
            message_id=uuid4(),
            message_type="task.start",
            correlation_id=self._source.correlation_id,
            causation_id=self._source.message_id,
            idempotency_key=f"task.start:{run_id}:{node_id}",
            tenant=self._source.tenant,
            subject=subject,
            sequence=None,
            payload={
                "task_id": str(task_id),
                "task_type": task_type,
                "node_id": str(node_id),
                "payload": payload,
                "credential_refs": {k: str(v) for k, v in credential_refs.items()},
                "resource_refs": {k: str(v) for k, v in resource_refs.items()},
                "budgets": budgets,
            },
        )
        exchange = await self._channel.get_exchange(MessagingNames.COMMANDS_EXCHANGE)
        body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        await exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=MessagingNames.TASK_START_ROUTING_KEY,
        )
        return task_id
