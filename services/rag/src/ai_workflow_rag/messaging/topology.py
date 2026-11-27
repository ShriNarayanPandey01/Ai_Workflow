from __future__ import annotations

import logging

import aio_pika

from ai_workflow_rag.messaging import constants as mq

logger = logging.getLogger(__name__)


async def declare_ingestion_queue(channel: aio_pika.abc.AbstractChannel):
    try:
        return await channel.declare_queue(
            mq.INGESTION_COMMANDS_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": mq.DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": "rejected",
            },
        )
    except aio_pika.exceptions.ChannelPreconditionFailed:
        logger.warning(
            "Queue %s already exists with different arguments; reusing existing queue",
            mq.INGESTION_COMMANDS_QUEUE,
        )
        if hasattr(channel, "reopen"):
            await channel.reopen()
        return await channel.declare_queue(mq.INGESTION_COMMANDS_QUEUE, passive=True)


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
