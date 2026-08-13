from __future__ import annotations

import enum
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg


class ClaimResult(enum.Enum):
    NEW = "new"
    DUPLICATE_COMPLETED = "duplicate_completed"
    DUPLICATE_FAILED = "duplicate_failed"
    DUPLICATE_IN_FLIGHT = "duplicate_in_flight"


# Default reclaim TTL; workers should pass max_run_seconds + buffer.
STALE_PROCESSING_INTERVAL = timedelta(seconds=360)


class PostgresInbox:
    def __init__(self, pool: asyncpg.Pool, *, stale_after: timedelta | None = None) -> None:
        self._pool = pool
        self._stale_after = stale_after or STALE_PROCESSING_INTERVAL

    async def claim(
        self,
        *,
        message_id: UUID,
        run_id: UUID,
        message_type: str,
    ) -> ClaimResult:
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO ee.worker_inbox (message_id, run_id, message_type, status)
                VALUES ($1, $2, $3, 'processing')
                ON CONFLICT (message_id) DO NOTHING
                RETURNING message_id
                """,
                message_id,
                run_id,
                message_type,
            )
            if inserted is not None:
                return ClaimResult.NEW

            row = await conn.fetchrow(
                "SELECT status, updated_at FROM ee.worker_inbox WHERE message_id = $1",
                message_id,
            )
            if row is None:
                return ClaimResult.NEW
            if row["status"] == "completed":
                return ClaimResult.DUPLICATE_COMPLETED
            if row["status"] == "failed":
                retried = await conn.fetchrow(
                    """
                    UPDATE ee.worker_inbox
                    SET status = 'processing', updated_at = NOW()
                    WHERE message_id = $1 AND status = 'failed'
                    RETURNING message_id
                    """,
                    message_id,
                )
                if retried is not None:
                    return ClaimResult.NEW
                return ClaimResult.DUPLICATE_FAILED
            stale_before = datetime.now(UTC) - self._stale_after
            updated_at = row["updated_at"]
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            if updated_at < stale_before:
                interval_seconds = int(self._stale_after.total_seconds())
                reclaimed = await conn.fetchrow(
                    """
                    UPDATE ee.worker_inbox
                    SET updated_at = NOW()
                    WHERE message_id = $1
                      AND status = 'processing'
                      AND updated_at < NOW() - make_interval(secs => $2)
                    RETURNING message_id
                    """,
                    message_id,
                    interval_seconds,
                )
                if reclaimed is not None:
                    return ClaimResult.NEW
            return ClaimResult.DUPLICATE_IN_FLIGHT

    async def mark_completed(self, *, message_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ee.worker_inbox
                SET status = 'completed', updated_at = NOW()
                WHERE message_id = $1
                """,
                message_id,
            )

    async def mark_failed(self, *, message_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ee.worker_inbox
                SET status = 'failed', updated_at = NOW()
                WHERE message_id = $1
                """,
                message_id,
            )
