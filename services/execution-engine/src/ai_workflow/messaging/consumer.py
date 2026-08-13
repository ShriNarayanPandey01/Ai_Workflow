from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import aio_pika

from ai_workflow.log_context import execution_log_extra
from ai_workflow.messaging.topology import declare_durable_queue

logger = logging.getLogger(__name__)

MessageHandler = Callable[[aio_pika.abc.AbstractIncomingMessage], Awaitable[None]]


async def connect_rabbitmq(
    url: str,
    *,
    attempts: int = 30,
    delay_seconds: float = 2.0,
    role: str,
) -> aio_pika.abc.AbstractRobustConnection:
    """Connect to RabbitMQ with bounded retries at process boot."""
    last_error: Exception | None = None
    extra = execution_log_extra(role=role)
    for attempt in range(1, attempts + 1):
        try:
            connection = await aio_pika.connect_robust(url)
            logger.info("Connected to RabbitMQ on attempt %s", attempt, extra=extra)
            return connection
        except Exception as exc:  # noqa: BLE001 - retry any connect failure at boot
            last_error = exc
            logger.warning(
                "RabbitMQ connect attempt %s/%s failed: %s",
                attempt,
                attempts,
                exc,
                extra=extra,
            )
            await asyncio.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


async def consume_queue(
    channel: aio_pika.abc.AbstractChannel,
    queue_name: str,
    handler: MessageHandler,
) -> aio_pika.abc.AbstractQueue:
    queue = await declare_durable_queue(channel, queue_name)
    await queue.consume(handler)
    return queue
