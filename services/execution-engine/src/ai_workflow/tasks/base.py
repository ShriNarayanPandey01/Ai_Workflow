from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from ai_workflow.contracts.common.types import JsonValue


@dataclass(frozen=True, slots=True)
class TaskCheckpoint:
    data: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskContext:
    run_id: UUID
    workspace_id: UUID
    project_id: UUID
    workflow_version_id: UUID | None
    node_id: UUID
    task_id: UUID
    attempt: int
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaskResult:
    outputs: dict[str, JsonValue] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class DurableTaskExecutor(Protocol):
    task_type: str

    async def run(
        self,
        context: TaskContext,
        payload: dict[str, JsonValue],
        checkpoint: TaskCheckpoint | None,
    ) -> TaskResult: ...
