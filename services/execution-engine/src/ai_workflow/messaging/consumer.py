from __future__ import annotations

from collections.abc import Awaitable, Callable

import aio_pika

from ai_workflow.messaging.topology import declare_durable_queue

MessageHandler = Callable[[aio_pika.abc.AbstractIncomingMessage], Awaitable[None]]


async def consume_queue(
    channel: aio_pika.abc.AbstractChannel,
    queue_name: str,
    handler: MessageHandler,
) -> aio_pika.abc.AbstractQueue:
    queue = await declare_durable_queue(channel, queue_name)
    await queue.consume(handler)
    return queue
