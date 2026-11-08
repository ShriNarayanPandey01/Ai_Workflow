from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.tasks.base import TaskCheckpoint

if TYPE_CHECKING:
    import asyncpg


class PostgresTaskCheckpointStore:
    """Persists per-task item progress so restarts skip completed work."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(
        self,
        *,
        task_id: UUID,
        run_id: UUID,
        node_id: UUID,
        task_type: str,
        data: dict[str, JsonValue],
    ) -> None:
        payload = json.dumps(data)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ee.task_checkpoints (
                    task_id, run_id, node_id, task_type, state, updated_at
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
                ON CONFLICT (task_id) DO UPDATE
                SET state = EXCLUDED.state, updated_at = NOW()
                """,
                task_id,
                run_id,
                node_id,
                task_type,
                payload,
            )

    async def load(self, task_id: UUID) -> TaskCheckpoint | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM ee.task_checkpoints WHERE task_id = $1",
                task_id,
            )
        if row is None:
            return None
        state = row["state"]
        if isinstance(state, str):
            state = json.loads(state)
        if not isinstance(state, dict):
            return TaskCheckpoint()
        return TaskCheckpoint(data=state)
