from __future__ import annotations

from datetime import UTC, datetime, timedelta
from socket import gethostname
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg


class LeaseError(RuntimeError):
    """Raised when a run lease cannot be acquired."""


class RunLeaseStore:
    """Exclusive per-run_id lease so two walkers cannot share a run."""

    def __init__(self, pool: asyncpg.Pool, *, owner: str | None = None) -> None:
        self._pool = pool
        self._owner = owner or gethostname()

    async def acquire(self, run_id: UUID, *, ttl: timedelta) -> None:
        expires = datetime.now(UTC) + ttl
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO ee.run_leases (run_id, owner, expires_at, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (run_id) DO UPDATE
                SET owner = EXCLUDED.owner,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                WHERE ee.run_leases.expires_at < NOW()
                   OR ee.run_leases.owner = EXCLUDED.owner
                RETURNING run_id
                """,
                run_id,
                self._owner,
                expires,
            )
        if row is None:
            msg = f"Run {run_id} is leased by another worker"
            raise LeaseError(msg)

    async def release(self, run_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ee.run_leases WHERE run_id = $1 AND owner = $2",
                run_id,
                self._owner,
            )
