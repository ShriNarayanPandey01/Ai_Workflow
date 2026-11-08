from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from ai_workflow.config.settings import SERVICE_ROOT
from ai_workflow.runtime.persistence.database import create_pool, run_migrations

pytestmark = pytest.mark.integration


@pytest.fixture
async def db_pool():
    try:
        pool = await create_pool("postgresql://aiw:aiw@localhost:5432/aiw")
        await run_migrations(pool, SERVICE_ROOT / "sql")
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_allocate_sequence_increments(db_pool) -> None:
    run_id = uuid4()

    async with db_pool.acquire() as conn:
        first = await conn.fetchrow(
            """
            INSERT INTO ee.run_sequences (run_id, last_sequence)
            VALUES ($1, 1)
            ON CONFLICT (run_id) DO UPDATE
            SET last_sequence = ee.run_sequences.last_sequence + 1
            RETURNING last_sequence
            """,
            run_id,
        )
        second = await conn.fetchrow(
            """
            INSERT INTO ee.run_sequences (run_id, last_sequence)
            VALUES ($1, 1)
            ON CONFLICT (run_id) DO UPDATE
            SET last_sequence = ee.run_sequences.last_sequence + 1
            RETURNING last_sequence
            """,
            run_id,
        )

    assert first is not None and int(first["last_sequence"]) == 1
    assert second is not None and int(second["last_sequence"]) == 2
