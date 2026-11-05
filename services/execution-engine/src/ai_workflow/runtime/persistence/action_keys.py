from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from ai_workflow.contracts.common.types import JsonValue

if TYPE_CHECKING:
    import asyncpg


class ActionKeyConflictError(ValueError):
    """Raised when a stored action key is replayed with a different fingerprint.

    A cache hit whose stored request fingerprint does not match the fingerprint
    of the request being made signals non-idempotent reuse of the same action
    key (e.g. a resumed run re-executing a side effect with changed inputs). The
    side effect is refused rather than silently returning the stale response.
    """


@dataclass(frozen=True, slots=True)
class ActionKeyRecord:
    """A persisted side-effect result keyed by its action key."""

    fingerprint: str
    response: dict[str, JsonValue]


class ActionKeyStore(Protocol):
    """Persists side-effect execution keys for idempotent HTTP actions.

    Keyed on an opaque ``action_key`` string so callers can scope idempotency
    however they need — per attempt for top-level nodes, or per for-each item so
    each item's side effect is cached independently instead of colliding on a
    shared ``(run_id, node_id, attempt)`` tuple.
    """

    async def get(self, *, action_key: str) -> ActionKeyRecord | None: ...

    async def put(
        self,
        *,
        action_key: str,
        run_id: UUID,
        node_id: UUID,
        attempt: int,
        fingerprint: str,
        response: dict[str, JsonValue],
    ) -> None: ...


class InMemoryActionKeyStore:
    """Process-local action key store for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, ActionKeyRecord] = {}

    async def get(self, *, action_key: str) -> ActionKeyRecord | None:
        return self._store.get(action_key)

    async def put(
        self,
        *,
        action_key: str,
        run_id: UUID,
        node_id: UUID,
        attempt: int,
        fingerprint: str,
        response: dict[str, JsonValue],
    ) -> None:
        del run_id, node_id, attempt
        if action_key not in self._store:
            self._store[action_key] = ActionKeyRecord(
                fingerprint=fingerprint,
                response=dict(response),
            )


class PostgresActionKeyStore:
    """PostgreSQL-backed action key store for production workers."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, *, action_key: str) -> ActionKeyRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT fingerprint, response
                FROM ee.action_execution_keys
                WHERE action_key = $1
                """,
                action_key,
            )
        if row is None:
            return None
        payload = row["response"]
        if isinstance(payload, str):
            parsed = json.loads(payload)
        else:
            parsed = payload
        if not isinstance(parsed, dict):
            return None
        return ActionKeyRecord(fingerprint=str(row["fingerprint"]), response=parsed)

    async def put(
        self,
        *,
        action_key: str,
        run_id: UUID,
        node_id: UUID,
        attempt: int,
        fingerprint: str,
        response: dict[str, JsonValue],
    ) -> None:
        payload = json.dumps(response)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ee.action_execution_keys (
                    action_key, run_id, node_id, attempt, fingerprint, response
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (action_key) DO NOTHING
                """,
                action_key,
                run_id,
                node_id,
                attempt,
                fingerprint,
                payload,
            )


def canonical_json(value: Any) -> str:
    """Serialize JSON for stable request fingerprints."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
