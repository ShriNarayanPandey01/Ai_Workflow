from __future__ import annotations

import aio_pika

from ai_workflow_rag.messaging import constants as mq


async def declare_ingestion_queue(channel: aio_pika.abc.AbstractChannel):
    return await channel.declare_queue(
        mq.INGESTION_COMMANDS_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": mq.DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": "rejected",
        },
    )


async def declare_topology(channel: aio_pika.abc.AbstractChannel) -> None:
    commands_exchange = await channel.declare_exchange(
        mq.COMMANDS_EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    await channel.declare_exchange(
        mq.EVENTS_EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    await channel.declare_exchange(
        mq.DEAD_LETTER_EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )

    ingestion_queue = await declare_ingestion_queue(channel)
    await ingestion_queue.bind(commands_exchange, routing_key=mq.DOCUMENT_INGEST_ROUTING_KEY)
    await ingestion_queue.bind(commands_exchange, routing_key=mq.DOCUMENT_DELETE_ROUTING_KEY)
