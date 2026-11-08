from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from ai_workflow.config.settings import SERVICE_ROOT
from ai_workflow.runtime.pause import PauseRegistry
from ai_workflow.runtime.persistence.database import create_pool, run_migrations

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_pause_state_is_shared_and_stale_commands_are_ignored() -> None:
    try:
        pool = await create_pool("postgresql://aiw:aiw@localhost:5432/aiw")
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    try:
        await run_migrations(pool, SERVICE_ROOT / "sql")
        writer = PauseRegistry(pool)
        reader = PauseRegistry(pool)
        run_id, pause_id = uuid4(), uuid4()
        assert await writer.apply(run_id, pause_id=pause_id, revision=1, requested=True)
        state = await reader.get(run_id)
        assert state is not None and state.requested and state.pause_id == pause_id
        assert await reader.apply(run_id, pause_id=pause_id, revision=2, requested=False)
        assert not await writer.apply(run_id, pause_id=pause_id, revision=1, requested=True)
        state = await writer.get(run_id)
        assert state is not None and not state.requested and state.revision == 2
    finally:
        await pool.close()
