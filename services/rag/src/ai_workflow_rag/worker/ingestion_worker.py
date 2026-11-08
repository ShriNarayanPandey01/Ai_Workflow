from __future__ import annotations

import asyncio
import logging

import aio_pika

from ai_workflow_rag.config.settings import SERVICE_ROOT, load_settings
from ai_workflow_rag.db import create_pool, run_migrations
from ai_workflow_rag.messaging import constants as mq
from ai_workflow_rag.messaging.topology import declare_topology
from ai_workflow_rag.messaging.validation import EnvelopeValidationError
from ai_workflow_rag.worker.ingestion_handler import (
    IngestionCommandHandler,
    MessageInFlightError,
    build_ingestion_handler,
)

logger = logging.getLogger(__name__)


async def _handle_message(
    handler: IngestionCommandHandler,
    message: aio_pika.abc.AbstractIncomingMessage,
) -> None:
    try:
        await handler.handle(message.body)
    except EnvelopeValidationError as exc:
        logger.warning("Rejecting invalid message: %s", exc)
        await message.reject(requeue=False)
        return
    except MessageInFlightError:
        logger.info("Message still in flight; requeueing")
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
    settings = load_settings()
    logging.basicConfig(level=settings.log_level)

    pool = await create_pool(settings.database_url)
    sql_dir = SERVICE_ROOT / "sql"
    applied = await run_migrations(pool, sql_dir)
    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied))

    connection = await _connect_rabbitmq(settings.rabbitmq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=5)
    await declare_topology(channel)

    handler = build_ingestion_handler(
        settings=settings,
        pool=pool,
        channel=channel,
    )

    queue = await channel.declare_queue(mq.INGESTION_COMMANDS_QUEUE, durable=True)

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        asyncio.create_task(_handle_message(handler, message))

    await queue.consume(on_message)
    logger.info("RAG worker listening on %s", mq.INGESTION_COMMANDS_QUEUE)

    try:
        await asyncio.Future()
    finally:
        await connection.close()
        await pool.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
