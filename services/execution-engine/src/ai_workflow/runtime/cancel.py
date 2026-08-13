from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg


@dataclass(frozen=True, slots=True)
class CancelRequest:
    """Recorded reason for a cooperative workflow cancellation."""

    reason: str


class CancelRegistry:
    """Per-run cooperative cancellation flags (asyncio-safe, optionally durable)."""

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        """Initialize an empty cooperative cancellation registry."""
        self._lock = asyncio.Lock()
        self._cancelled: dict[UUID, CancelRequest] = {}
        self._events: dict[UUID, asyncio.Event] = {}
        self._pool = pool

    def cancel_check(self, run_id: UUID) -> Callable[[], bool]:
        """Return a sync predicate nodes can poll after awaits."""
        return lambda: run_id in self._cancelled

    def event_for(self, run_id: UUID) -> asyncio.Event:
        """Return (creating if needed) the cancel event for a run."""
        event = self._events.get(run_id)
        if event is None:
            event = asyncio.Event()
            self._events[run_id] = event
            if run_id in self._cancelled:
                event.set()
        return event

    async def request_cancel(self, run_id: UUID, *, reason: str) -> None:
        """Mark a run for cooperative cancellation and persist when a pool is set."""
        async with self._lock:
            self._cancelled[run_id] = CancelRequest(reason=reason)
            event = self._events.get(run_id)
            if event is not None:
                event.set()
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO ee.run_cancels (run_id, reason)
                    VALUES ($1, $2)
                    ON CONFLICT (run_id) DO UPDATE SET reason = EXCLUDED.reason
                    """,
                    run_id,
                    reason,
                )

    async def is_cancelled(self, run_id: UUID) -> CancelRequest | None:
        """Return the cancel request for a run, if one is active."""
        async with self._lock:
            cached = self._cancelled.get(run_id)
        if cached is not None:
            return cached
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT reason FROM ee.run_cancels WHERE run_id = $1",
                run_id,
            )
        if row is None:
            return None
        request = CancelRequest(reason=str(row["reason"]))
        async with self._lock:
            self._cancelled[run_id] = request
            event = self._events.get(run_id)
            if event is not None:
                event.set()
        return request

    async def refresh_from_db(self) -> None:
        """Load durable cancel flags so in-flight nodes on this process observe them."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT run_id, reason FROM ee.run_cancels")
        async with self._lock:
            for row in rows:
                run_id = row["run_id"]
                request = CancelRequest(reason=str(row["reason"]))
                self._cancelled[run_id] = request
                event = self._events.get(run_id)
                if event is not None:
                    event.set()

    async def clear(self, run_id: UUID) -> None:
        """Drop any stored cancel flag after a run finishes."""
        async with self._lock:
            self._cancelled.pop(run_id, None)
            self._events.pop(run_id, None)
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM ee.run_cancels WHERE run_id = $1",
                    run_id,
                )
