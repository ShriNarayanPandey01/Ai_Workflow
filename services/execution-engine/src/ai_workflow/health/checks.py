from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import aio_pika
import asyncpg

from ai_workflow.config.settings import Settings

PostgresCheck = Callable[[str], Awaitable[bool]]
RabbitCheck = Callable[[str], Awaitable[bool]]


async def _default_postgres_check(database_url: str) -> bool:
    conn = await asyncpg.connect(database_url, timeout=5)
    try:
        await conn.execute("SELECT 1")
        return True
    finally:
        await conn.close()


async def _default_rabbitmq_check(rabbitmq_url: str) -> bool:
    connection = await aio_pika.connect_robust(rabbitmq_url, timeout=5)
    try:
        return not connection.is_closed
    finally:
        await connection.close()


async def check_readiness(
    settings: Settings,
    *,
    postgres_check: PostgresCheck = _default_postgres_check,
    rabbit_check: RabbitCheck = _default_rabbitmq_check,
) -> tuple[bool, dict[str, str]]:
    postgres_task = postgres_check(settings.database_url)
    rabbit_task = rabbit_check(settings.rabbitmq_url)
    postgres_ok, rabbit_ok = await asyncio.gather(
        postgres_task,
        rabbit_task,
        return_exceptions=True,
    )

    components: dict[str, str] = {}

    if isinstance(postgres_ok, BaseException) or not postgres_ok:
        components["postgres"] = "DOWN"
    else:
        components["postgres"] = "UP"

    if isinstance(rabbit_ok, BaseException) or not rabbit_ok:
        components["rabbitmq"] = "DOWN"
    else:
        components["rabbitmq"] = "UP"

    ready = components["postgres"] == "UP" and components["rabbitmq"] == "UP"
    return ready, components
