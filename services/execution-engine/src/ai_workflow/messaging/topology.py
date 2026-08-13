from __future__ import annotations

import aio_pika

from ai_workflow.messaging import constants as mq


def durable_queue_arguments() -> dict[str, str]:
    """Args for work queues that dead-letter rejected messages."""
    return {
        "x-dead-letter-exchange": mq.DEAD_LETTER_EXCHANGE,
        "x-dead-letter-routing-key": "rejected",
    }


async def declare_durable_queue(
    channel: aio_pika.abc.AbstractChannel,
    name: str,
) -> aio_pika.abc.AbstractQueue:
    """Declare a durable work queue with the same DLQ args as topology."""
    return await channel.declare_queue(
        name,
        durable=True,
        arguments=durable_queue_arguments(),
    )


async def declare_topology(channel: aio_pika.abc.AbstractChannel) -> None:
    commands_exchange = await channel.declare_exchange(
        mq.COMMANDS_EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    events_exchange = await channel.declare_exchange(
        mq.EVENTS_EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    dead_letter_exchange = await channel.declare_exchange(
        mq.DEAD_LETTER_EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )

    execution_queue = await declare_durable_queue(channel, mq.EXECUTION_COMMANDS_QUEUE)
    await execution_queue.bind(commands_exchange, routing_key=mq.EXECUTION_COMMANDS_BINDING)

    task_commands = await declare_durable_queue(channel, mq.TASK_COMMANDS_QUEUE)
    await task_commands.bind(commands_exchange, routing_key=mq.TASK_COMMANDS_BINDING)

    task_results = await declare_durable_queue(channel, mq.TASK_RESULTS_QUEUE)
    await task_results.bind(events_exchange, routing_key="task.#")

    control_events_queue = await channel.declare_queue(
        mq.CONTROL_EVENTS_QUEUE,
        durable=True,
    )
    await control_events_queue.bind(events_exchange, routing_key=mq.CONTROL_EVENTS_BINDING)

    dead_queue = await channel.declare_queue(mq.DEAD_LETTER_QUEUE, durable=True)
    await dead_queue.bind(dead_letter_exchange, routing_key=mq.DEAD_LETTER_BINDING)
