from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from ai_workflow.config.settings import SERVICE_ROOT
from ai_workflow.messaging.inbox import ClaimResult, PostgresInbox
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
async def test_inbox_claim_dedup(db_pool) -> None:
    inbox = PostgresInbox(db_pool)
    message_id = uuid4()
    run_id = uuid4()

    first = await inbox.claim(
        message_id=message_id,
        run_id=run_id,
        message_type="execution.start",
    )
    assert first is ClaimResult.NEW

    second = await inbox.claim(
        message_id=message_id,
        run_id=run_id,
        message_type="execution.start",
    )
    assert second is ClaimResult.DUPLICATE_IN_FLIGHT

    await inbox.mark_completed(message_id=message_id)

    third = await inbox.claim(
        message_id=message_id,
        run_id=run_id,
        message_type="execution.start",
    )
    assert third is ClaimResult.DUPLICATE_COMPLETED
