from __future__ import annotations

import json
from uuid import UUID, uuid4

import aio_pika

from ai_workflow_rag.messaging import constants as mq
from ai_workflow_rag.messaging.envelope import Tenant, build_document_event_envelope


class DocumentEventPublisher:
    def __init__(
        self,
        *,
        channel: aio_pika.abc.AbstractChannel,
        tenant: Tenant,
        correlation_id: UUID,
        causation_id: UUID,
        document_id: UUID,
    ) -> None:
        self._channel = channel
        self._tenant = tenant
        self._correlation_id = correlation_id
        self._causation_id = causation_id
        self._document_id = document_id

    async def publish(
        self,
        *,
        message_type: str,
        routing_key: str,
        payload: dict,
        idempotency_suffix: str,
    ) -> None:
        envelope = build_document_event_envelope(
            message_id=uuid4(),
            message_type=message_type,
            correlation_id=self._correlation_id,
            causation_id=self._causation_id,
            idempotency_key=f"{idempotency_suffix}:{self._document_id}",
            tenant=self._tenant,
            document_id=self._document_id,
            payload=payload,
        )
        exchange = await self._channel.get_exchange(mq.EVENTS_EXCHANGE)
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(envelope).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
