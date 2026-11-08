from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import aio_pika

from ai_workflow.log_context import execution_log_extra

logger = logging.getLogger(__name__)

MessageHandler = Callable[[aio_pika.abc.AbstractIncomingMessage], Awaitable[None]]


class MessagingNames:
    """RabbitMQ exchange, queue, and routing-key names for this service."""

    COMMANDS_EXCHANGE = "aiw.commands.v1"
    EVENTS_EXCHANGE = "aiw.events.v1"
    DEAD_LETTER_EXCHANGE = "aiw.dead.v1"

    EXECUTION_COMMANDS_QUEUE = "aiw.execution.commands.v1"
    CONTROL_EVENTS_QUEUE = "aiw.control.events.v1"

    EXECUTION_START_ROUTING_KEY = "execution.start.v1"
    EXECUTION_RESUME_ROUTING_KEY = "execution.resume.v1"
    EXECUTION_CANCEL_ROUTING_KEY = "execution.cancel.v1"
    EXECUTION_STARTED_ROUTING_KEY = "execution.started.v1"
    EXECUTION_WAITING_ROUTING_KEY = "execution.waiting.v1"
    EXECUTION_COMPLETED_ROUTING_KEY = "execution.completed.v1"
    EXECUTION_FAILED_ROUTING_KEY = "execution.failed.v1"
    EXECUTION_CANCELLED_ROUTING_KEY = "execution.cancelled.v1"
    NODE_STARTED_ROUTING_KEY = "node.started.v1"
    NODE_COMPLETED_ROUTING_KEY = "node.completed.v1"
    NODE_FAILED_ROUTING_KEY = "node.failed.v1"

    TASK_COMMANDS_QUEUE = "aiw.task.commands.v1"
    TASK_RESULTS_QUEUE = "aiw.task.results.v1"
    DEAD_LETTER_QUEUE = "aiw.dead.q.v1"

    TASK_START_ROUTING_KEY = "task.start.v1"
    TASK_CANCEL_ROUTING_KEY = "task.cancel.v1"
    TASK_COMPLETED_ROUTING_KEY = "task.completed.v1"
    TASK_FAILED_ROUTING_KEY = "task.failed.v1"
    TASK_PROGRESS_ROUTING_KEY = "task.progress.v1"

    EXECUTION_COMMANDS_BINDING = "execution.*.v1"
    TASK_COMMANDS_BINDING = "task.*.v1"
    CONTROL_EVENTS_BINDING = "#"
    DEAD_LETTER_BINDING = "#"


class RabbitBroker:
    """Connects to RabbitMQ, declares topology, and consumes work queues."""

    def __init__(self) -> None:
        self._names = MessagingNames

    def _durable_queue_arguments(self) -> dict[str, str]:
        return {
            "x-dead-letter-exchange": self._names.DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": "rejected",
        }

    async def connect(
        self,
        url: str,
        *,
        role: str,
        attempts: int = 30,
        delay_seconds: float = 2.0,
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

    async def declare_durable_queue(
        self,
        channel: aio_pika.abc.AbstractChannel,
        name: str,
    ) -> aio_pika.abc.AbstractQueue:
        """Declare a durable work queue with the same DLQ args as topology."""
        return await channel.declare_queue(
            name,
            durable=True,
            arguments=self._durable_queue_arguments(),
        )

    async def declare_topology(self, channel: aio_pika.abc.AbstractChannel) -> None:
        names = self._names
        commands_exchange = await channel.declare_exchange(
            names.COMMANDS_EXCHANGE,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        events_exchange = await channel.declare_exchange(
            names.EVENTS_EXCHANGE,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        dead_letter_exchange = await channel.declare_exchange(
            names.DEAD_LETTER_EXCHANGE,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        execution_queue = await self.declare_durable_queue(
            channel, names.EXECUTION_COMMANDS_QUEUE
        )
        await execution_queue.bind(
            commands_exchange, routing_key=names.EXECUTION_COMMANDS_BINDING
        )

        task_commands = await self.declare_durable_queue(channel, names.TASK_COMMANDS_QUEUE)
        await task_commands.bind(commands_exchange, routing_key=names.TASK_COMMANDS_BINDING)

        task_results = await self.declare_durable_queue(channel, names.TASK_RESULTS_QUEUE)
        await task_results.bind(events_exchange, routing_key="task.#")

        control_events_queue = await channel.declare_queue(
            names.CONTROL_EVENTS_QUEUE,
            durable=True,
        )
        await control_events_queue.bind(
            events_exchange, routing_key=names.CONTROL_EVENTS_BINDING
        )

        dead_queue = await channel.declare_queue(names.DEAD_LETTER_QUEUE, durable=True)
        await dead_queue.bind(dead_letter_exchange, routing_key=names.DEAD_LETTER_BINDING)

    async def consume(
        self,
        channel: aio_pika.abc.AbstractChannel,
        queue_name: str,
        handler: MessageHandler,
    ) -> aio_pika.abc.AbstractQueue:
        queue = await self.declare_durable_queue(channel, queue_name)
        await queue.consume(handler)
        return queue
