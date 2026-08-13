from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from ai_workflow.config.settings import SERVICE_ROOT
from ai_workflow.runtime.action_keys import PostgresActionKeyStore
from ai_workflow.runtime.db import create_pool, run_migrations

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
async def test_postgres_action_key_store_round_trip(db_pool) -> None:
    store = PostgresActionKeyStore(db_pool)
    run_id = uuid4()
    node_id = uuid4()
    action_key = f"{run_id}:{node_id}:1"
    response = {
        "status_code": 200,
        "headers": {"content-type": "application/json"},
        "body": {"ok": True},
        "body_text": None,
    }

    assert await store.get(action_key=action_key) is None
    await store.put(
        run_id=run_id,
        node_id=node_id,
        attempt=1,
        action_key=action_key,
        fingerprint="abc123",
        response=response,
    )
    loaded = await store.get(action_key=action_key)
    assert loaded is not None
    assert loaded.response == response
    assert loaded.fingerprint == "abc123"

    await store.put(
        run_id=run_id,
        node_id=node_id,
        attempt=1,
        action_key=action_key,
        fingerprint="different",
        response={"status_code": 500, "headers": {}, "body": None, "body_text": "fail"},
    )
    loaded_again = await store.get(action_key=action_key)
    assert loaded_again is not None
    assert loaded_again.response == response
    assert loaded_again.fingerprint == "abc123"
