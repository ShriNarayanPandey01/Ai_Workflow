from __future__ import annotations

import asyncio
import logging

import aio_pika

from ai_workflow.config.settings import SERVICE_ROOT, load_settings, require_service_role
from ai_workflow.messaging import constants as mq
from ai_workflow.messaging.topology import declare_durable_queue, declare_topology
from ai_workflow.messaging.validation import EnvelopeValidationError
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.db import create_pool, run_migrations
from ai_workflow.worker.handler import (
    ExecutionCommandHandler,
    MessageInFlightError,
    MessageNotReadyError,
    build_execution_handler,
)

logger = logging.getLogger(__name__)


async def _handle_message(
    handler: ExecutionCommandHandler,
    message: aio_pika.abc.AbstractIncomingMessage,
) -> None:
    try:
        await handler.handle(message.body)
    except EnvelopeValidationError as exc:
        logger.warning("Rejecting invalid message: %s", exc)
        await message.reject(requeue=False)
        return
    except MessageInFlightError:
        # Another delivery is already claimed in ee.worker_inbox. Requeueing
        # here livelocks: the duplicate is nacked, immediately redelivered, and
        # starves the in-flight handler (and the e2e event loop).
        logger.info("Message still in flight; acknowledging duplicate delivery")
        await message.ack()
        return
    except MessageNotReadyError as exc:
        logger.info("Requeueing until parent is waiting: %s", exc)
        await message.nack(requeue=True)
        return
    except Exception:
        logger.exception("Transient failure processing message")
        await message.nack(requeue=True)
        return

    await message.ack()


async def _connect_rabbitmq(url: str, *, attempts: int = 30, delay_seconds: float = 2.0):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            connection = await aio_pika.connect_robust(url)
            logger.info("Connected to RabbitMQ on attempt %s", attempt)
            return connection
        except Exception as exc:  # noqa: BLE001 - retry any connect failure at boot
            last_error = exc
            logger.warning(
                "RabbitMQ connect attempt %s/%s failed: %s",
                attempt,
                attempts,
                exc,
            )
            await asyncio.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


async def run_worker() -> None:
    """Boot the execution worker and consume workflow command messages."""
    settings = load_settings()
    require_service_role(settings, "execution-worker")
    logging.basicConfig(level=settings.log_level)

    pool = await create_pool(
        settings.database_url,
        max_size=max(settings.worker_prefetch + 4, 10),
    )
    sql_dir = SERVICE_ROOT / "sql"
    applied = await run_migrations(pool, sql_dir)
    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied))

    cancel_registry = CancelRegistry(pool)

    connection = await _connect_rabbitmq(settings.rabbitmq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.worker_prefetch)
    await declare_topology(channel)

    handler = build_execution_handler(
        settings=settings,
        pool=pool,
        channel=channel,
        cancel_registry=cancel_registry,
    )

    command_queue = await declare_durable_queue(channel, mq.EXECUTION_COMMANDS_QUEUE)
    results_queue = await declare_durable_queue(channel, mq.TASK_RESULTS_QUEUE)
    semaphore = asyncio.Semaphore(settings.worker_prefetch)

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        async def _run() -> None:
            async with semaphore:
                await _handle_message(handler, message)

        asyncio.create_task(_run())

    await command_queue.consume(on_message)
    await results_queue.consume(on_message)
    logger.info(
        "Execution worker listening on %s and %s",
        mq.EXECUTION_COMMANDS_QUEUE,
        mq.TASK_RESULTS_QUEUE,
    )

    async def refresh_cancels() -> None:
        while True:
            await cancel_registry.refresh_from_db()
            await asyncio.sleep(1.0)

    refresh_task = asyncio.create_task(refresh_cancels())

    try:
        await asyncio.Future()
    finally:
        refresh_task.cancel()
        await handler.aclose()
        await connection.close()
        await pool.close()


def main() -> None:
    """CLI entrypoint for the execution worker process."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
