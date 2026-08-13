from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from ai_workflow.runtime.for_each_runtime import FOREACH_FRAMES_KEY
from ai_workflow.runtime.scheduler_state import DEFINITION_KEY, INTERRUPT_KEY, SCHEDULER_KEY
from ai_workflow.runtime.state import WorkflowState

if TYPE_CHECKING:
    import asyncpg

CHECKPOINT_SCHEMA_VERSION = 1
DEFINITION_HASH_KEY = "_definition_hash"


class Checkpointer(Protocol):
    """Persists and restores workflow state keyed by run thread_id."""

    async def save(self, *, thread_id: UUID, state: WorkflowState) -> None: ...

    async def load(self, *, thread_id: UUID) -> WorkflowState | None: ...


def migrate_checkpoint(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a checkpoint blob to the current envelope schema.

    v0 (unversioned) stored scheduler, interrupt, foreach frames, and the full
    definition under ``runtime`` keys prefixed with ``_``. v1 lifts those to
    envelope fields and keeps ``runtime`` for run-scoped metadata.
    """
    if data.get("schema_version") == CHECKPOINT_SCHEMA_VERSION:
        runtime = dict(data.get("runtime") or {})
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "definition_hash": data.get("definition_hash") or runtime.get(DEFINITION_HASH_KEY),
            "scheduler": data.get("scheduler"),
            "interrupt": data.get("interrupt"),
            "foreach": data.get("foreach"),
            "definition": data.get("definition"),
            "node_outputs": dict(data.get("node_outputs") or {}),
            "loop_iterations": dict(data.get("loop_iterations") or {}),
            "task_refs": dict(data.get("task_refs") or {}),
            "runtime": runtime,
        }

    runtime = dict(data.get("runtime") or {})
    scheduler = runtime.pop(SCHEDULER_KEY, None)
    interrupt = runtime.pop(INTERRUPT_KEY, None)
    foreach = runtime.pop(FOREACH_FRAMES_KEY, None)
    definition = runtime.pop(DEFINITION_KEY, None)
    definition_hash = runtime.pop(DEFINITION_HASH_KEY, None)
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "definition_hash": definition_hash,
        "scheduler": scheduler,
        "interrupt": interrupt,
        "foreach": foreach,
        "definition": definition,
        "node_outputs": dict(data.get("node_outputs") or {}),
        "loop_iterations": dict(data.get("loop_iterations") or {}),
        "task_refs": dict(data.get("task_refs") or {}),
        "runtime": runtime,
    }


def state_to_dict(state: WorkflowState) -> dict[str, Any]:
    """Serialize workflow state into the versioned checkpoint envelope."""
    runtime = dict(state.runtime)
    scheduler = runtime.pop(SCHEDULER_KEY, None)
    interrupt = runtime.pop(INTERRUPT_KEY, None)
    foreach = runtime.pop(FOREACH_FRAMES_KEY, None)
    definition = runtime.pop(DEFINITION_KEY, None)
    definition_hash = runtime.pop(DEFINITION_HASH_KEY, None)
    envelope: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "definition_hash": definition_hash,
        "scheduler": scheduler,
        "interrupt": interrupt,
        "foreach": foreach,
        "node_outputs": state.node_outputs,
        "loop_iterations": state.loop_iterations,
        "task_refs": state.task_refs,
        "runtime": runtime,
    }
    if definition is not None:
        envelope["definition"] = definition
    return envelope


def state_from_dict(data: dict[str, Any]) -> WorkflowState:
    """Deserialize workflow state from a checkpoint dictionary (any schema)."""
    envelope = migrate_checkpoint(data)
    runtime = dict(envelope.get("runtime") or {})
    if envelope.get("scheduler") is not None:
        runtime[SCHEDULER_KEY] = envelope["scheduler"]
    if envelope.get("interrupt") is not None:
        runtime[INTERRUPT_KEY] = envelope["interrupt"]
    if envelope.get("foreach") is not None:
        runtime[FOREACH_FRAMES_KEY] = envelope["foreach"]
    if envelope.get("definition") is not None:
        runtime[DEFINITION_KEY] = envelope["definition"]
    if envelope.get("definition_hash"):
        runtime[DEFINITION_HASH_KEY] = envelope["definition_hash"]
    return WorkflowState(
        node_outputs=dict(envelope.get("node_outputs") or {}),
        loop_iterations=dict(envelope.get("loop_iterations") or {}),
        task_refs=dict(envelope.get("task_refs") or {}),
        runtime=runtime,
    )


class InMemoryCheckpointer:
    """Process-local checkpointer used in tests and ephemeral runs."""

    def __init__(self) -> None:
        """Create an empty in-memory checkpoint store."""
        self._store: dict[UUID, WorkflowState] = {}

    async def save(self, *, thread_id: UUID, state: WorkflowState) -> None:
        """Persist a workflow state snapshot in process memory."""
        self._store[thread_id] = state.snapshot()

    async def load(self, *, thread_id: UUID) -> WorkflowState | None:
        """Load a previously saved in-memory workflow state snapshot."""
        stored = self._store.get(thread_id)
        if stored is None:
            return None
        return deepcopy(stored)


class PostgresCheckpointer:
    """PostgreSQL-backed checkpointer keyed by run_id (thread_id)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the checkpointer to a PostgreSQL connection pool."""
        self._pool = pool

    async def save(self, *, thread_id: UUID, state: WorkflowState) -> None:
        """Upsert a workflow state snapshot into PostgreSQL."""
        envelope = state_to_dict(state.snapshot())
        payload = json.dumps(envelope)
        definition_hash = envelope.get("definition_hash")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ee.workflow_checkpoints (thread_id, state, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (thread_id) DO UPDATE
                SET state = EXCLUDED.state, updated_at = NOW()
                """,
                thread_id,
                payload,
            )
            if definition_hash:
                await conn.execute(
                    """
                    UPDATE ee.workflow_checkpoints
                    SET definition_hash = $2
                    WHERE thread_id = $1
                    """,
                    thread_id,
                    str(definition_hash),
                )

    async def load(self, *, thread_id: UUID) -> WorkflowState | None:
        """Load a workflow state snapshot from PostgreSQL, if present."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM ee.workflow_checkpoints WHERE thread_id = $1",
                thread_id,
            )
        if row is None:
            return None
        state_data = row["state"]
        if isinstance(state_data, str):
            state_data = json.loads(state_data)
        return state_from_dict(dict(state_data))
