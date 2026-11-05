from __future__ import annotations

import asyncio
import logging

import aio_pika

from ai_workflow.config.settings import SERVICE_ROOT, load_settings, require_service_role
from ai_workflow.log_context import execution_log_extra
from ai_workflow.messaging.broker import MessagingNames, RabbitBroker
from ai_workflow.messaging.envelope import EnvelopeValidationError
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.db import create_pool, run_migrations
from ai_workflow.worker.handler import (
    ExecutionCommandHandler,
    MessageInFlightError,
    MessageNotReadyError,
    build_execution_handler,
)

logger = logging.getLogger(__name__)
_ROLE = "execution-worker"


async def _handle_message(
    handler: ExecutionCommandHandler,
    message: aio_pika.abc.AbstractIncomingMessage,
) -> None:
    extra = execution_log_extra(role=_ROLE)
    try:
        await handler.handle(message.body)
    except EnvelopeValidationError as exc:
        logger.warning("Rejecting invalid message: %s", exc, extra=extra)
        await message.reject(requeue=False)
        return
    except MessageInFlightError:
        # Another delivery is already claimed in ee.worker_inbox. Requeueing
        # here livelocks: the duplicate is nacked, immediately redelivered, and
        # starves the in-flight handler (and the e2e event loop).
        logger.info("Message still in flight; acknowledging duplicate delivery", extra=extra)
        await message.ack()
        return
    except MessageNotReadyError as exc:
        logger.info("Requeueing until parent is waiting: %s", exc, extra=extra)
        await message.nack(requeue=True)
        return
    except Exception:
        logger.exception("Transient failure processing message", extra=extra)
        await message.nack(requeue=True)
        return

    await message.ack()


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
    extra = execution_log_extra(role=_ROLE)
    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied), extra=extra)

    cancel_registry = CancelRegistry(pool)
    # IGNORE THIS COMMENT: can we have a pause registry as well for pausing workflows?
    broker = RabbitBroker()
    connection = await broker.connect(settings.rabbitmq_url, role=_ROLE)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.worker_prefetch)
    await broker.declare_topology(channel)

    handler = build_execution_handler(
        settings=settings,
        pool=pool,
        channel=channel,
        cancel_registry=cancel_registry,
    )

    semaphore = asyncio.Semaphore(settings.worker_prefetch)

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        async def _run() -> None:
            async with semaphore:
                await _handle_message(handler, message)

        asyncio.create_task(_run())

    await broker.consume(channel, MessagingNames.EXECUTION_COMMANDS_QUEUE, on_message)
    await broker.consume(channel, MessagingNames.TASK_RESULTS_QUEUE, on_message)
    logger.info(
        "Execution worker listening on %s and %s",
        MessagingNames.EXECUTION_COMMANDS_QUEUE,
        MessagingNames.TASK_RESULTS_QUEUE,
        extra=extra,
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
