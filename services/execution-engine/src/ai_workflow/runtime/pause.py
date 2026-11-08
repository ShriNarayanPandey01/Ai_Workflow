from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg


@dataclass(frozen=True, slots=True)
class PauseState:
    """The latest manual pause control revision for a run."""

    pause_id: UUID
    revision: int
    requested: bool


class PauseRegistry:
    """Versioned manual pause requests, optionally shared through Postgres.

    This registry records intent only. A caller must checkpoint and quiesce the
    run before reporting it as paused.
    """

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._pool = pool
        self._lock = asyncio.Lock()
        self._states: dict[UUID, PauseState] = {}

    async def apply(
        self, run_id: UUID, *, pause_id: UUID, revision: int, requested: bool
    ) -> bool:
        """Apply a newer control revision; reject stale or mismatched unpauses.

        A first-seen unpause is retained as a tombstone to prevent a delayed
        earlier pause delivery from reactivating the run.
        """
        if revision < 1:
            raise ValueError("Pause revision must be positive")
        if self._pool is None:
            async with self._lock:
                current = self._states.get(run_id)
                if current is not None and (
                    revision <= current.revision
                    or (not requested and current.pause_id != pause_id)
                ):
                    return False
                self._states[run_id] = PauseState(pause_id, revision, requested)
                return True

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO ee.run_pause_requests (run_id, pause_id, revision, requested)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (run_id) DO UPDATE
                SET pause_id = EXCLUDED.pause_id,
                    revision = EXCLUDED.revision,
                    requested = EXCLUDED.requested,
                    updated_at = NOW()
                WHERE EXCLUDED.revision > ee.run_pause_requests.revision
                  AND (EXCLUDED.requested OR
                       EXCLUDED.pause_id = ee.run_pause_requests.pause_id)
                RETURNING run_id
                """,
                run_id,
                pause_id,
                revision,
                requested,
            )
        return row is not None

    async def get(self, run_id: UUID) -> PauseState | None:
        """Read the latest state directly from Postgres when a pool is set."""
        if self._pool is None:
            async with self._lock:
                return self._states.get(run_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT pause_id, revision, requested FROM ee.run_pause_requests WHERE run_id = $1",
                run_id,
            )
        if row is None:
            return None
        return PauseState(row["pause_id"], row["revision"], row["requested"])
