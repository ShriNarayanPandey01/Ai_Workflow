from __future__ import annotations

import enum
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

STALE_PROCESSING_INTERVAL = timedelta(seconds=60)


class ClaimResult(enum.Enum):
    NEW = "new"
    DUPLICATE_COMPLETED = "duplicate_completed"
    DUPLICATE_IN_FLIGHT = "duplicate_in_flight"


class PostgresInbox:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def claim(
        self,
        *,
        message_id: UUID,
        document_id: UUID,
        message_type: str,
    ) -> ClaimResult:
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO rag.worker_inbox (message_id, document_id, message_type, status)
                VALUES ($1, $2, $3, 'processing')
                ON CONFLICT (message_id) DO NOTHING
                RETURNING message_id
                """,
                message_id,
                document_id,
                message_type,
            )
            if inserted is not None:
                return ClaimResult.NEW

            row = await conn.fetchrow(
                "SELECT status, updated_at FROM rag.worker_inbox WHERE message_id = $1",
                message_id,
            )
            if row is None:
                return ClaimResult.NEW
            if row["status"] in ("completed", "failed"):
                return ClaimResult.DUPLICATE_COMPLETED
            stale_before = datetime.now(UTC) - STALE_PROCESSING_INTERVAL
            updated_at = row["updated_at"]
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            if updated_at < stale_before:
                reclaimed = await conn.fetchrow(
                    """
                    UPDATE rag.worker_inbox
                    SET updated_at = NOW()
                    WHERE message_id = $1
                      AND status = 'processing'
                      AND updated_at < NOW() - INTERVAL '60 seconds'
                    RETURNING message_id
                    """,
                    message_id,
                )
                if reclaimed is not None:
                    return ClaimResult.NEW
            return ClaimResult.DUPLICATE_IN_FLIGHT

    async def mark_completed(self, *, message_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE rag.worker_inbox
                SET status = 'completed', updated_at = NOW()
                WHERE message_id = $1
                """,
                message_id,
            )

    async def mark_failed(self, *, message_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE rag.worker_inbox
                SET status = 'failed', updated_at = NOW()
                WHERE message_id = $1
                """,
                message_id,
            )
