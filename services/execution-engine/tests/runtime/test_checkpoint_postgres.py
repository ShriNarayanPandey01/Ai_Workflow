from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from ai_workflow.config.settings import SERVICE_ROOT
from ai_workflow.runtime.checkpoint import PostgresCheckpointer, state_from_dict, state_to_dict
from ai_workflow.runtime.db import create_pool, run_migrations
from ai_workflow.runtime.state import WorkflowState

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


def test_state_round_trip() -> None:
    state = WorkflowState(
        node_outputs={"node-1": {"value": {"order_id": "ord-1"}}},
        runtime={"run_input": {"order_id": "ord-1"}},
    )
    restored = state_from_dict(state_to_dict(state))
    assert restored.node_outputs == state.node_outputs
    assert restored.runtime == state.runtime


@pytest.mark.asyncio
async def test_postgres_checkpointer_save_load(db_pool) -> None:
    checkpointer = PostgresCheckpointer(db_pool)
    thread_id = uuid4()
    state = WorkflowState(runtime={"run_input": {"order_id": "ord-42"}})

    await checkpointer.save(thread_id=thread_id, state=state)
    loaded = await checkpointer.load(thread_id=thread_id)

    assert loaded is not None
    assert loaded.runtime == state.runtime
