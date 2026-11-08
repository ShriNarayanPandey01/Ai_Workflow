from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Protocol

from ai_workflow.contracts.common.types import JsonValue

if TYPE_CHECKING:
    import asyncpg


def hash_definition(document: dict[str, JsonValue] | dict[str, Any]) -> str:
    """Return a stable SHA-256 hex digest of a workflow definition document."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DefinitionStore(Protocol):
    """Persists immutable workflow documents keyed by definition_hash."""

    async def put(self, document: dict[str, Any]) -> str: ...

    async def get(self, definition_hash: str) -> dict[str, Any] | None: ...


class InMemoryDefinitionStore:
    """Process-local definition store for tests and in-process runs."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def put(self, document: dict[str, Any]) -> str:
        digest = hash_definition(document)
        self._store[digest] = document
        return digest

    async def get(self, definition_hash: str) -> dict[str, Any] | None:
        stored = self._store.get(definition_hash)
        return dict(stored) if stored is not None else None


class PostgresDefinitionStore:
    """PostgreSQL-backed immutable definition store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def put(self, document: dict[str, Any]) -> str:
        digest = hash_definition(document)
        payload = json.dumps(document)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ee.workflow_definitions (definition_hash, document)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (definition_hash) DO NOTHING
                """,
                digest,
                payload,
            )
        return digest

    async def get(self, definition_hash: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT document FROM ee.workflow_definitions WHERE definition_hash = $1",
                definition_hash,
            )
        if row is None:
            return None
        document = row["document"]
        if isinstance(document, str):
            parsed = json.loads(document)
        else:
            parsed = document
        return dict(parsed) if isinstance(parsed, dict) else None
