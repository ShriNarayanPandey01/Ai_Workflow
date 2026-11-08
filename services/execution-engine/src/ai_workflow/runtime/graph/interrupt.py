from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ai_workflow.contracts.common.types import JsonValue


@dataclass(frozen=True, slots=True)
class WorkflowInterrupt(Exception):
    """Raised by human or durable-task nodes to pause execution."""

    interrupt_id: UUID
    waiting_reason: Literal["HUMAN", "TASK"]
    node_id: UUID
    approval_id: UUID | None
    node_type: str
    approval_request: dict[str, JsonValue]
    task_id: UUID | None = None

    def __str__(self) -> str:
        """Return a concise debug representation of the interrupt."""
        return (
            f"WorkflowInterrupt(node={self.node_id}, "
            f"interrupt={self.interrupt_id}, reason={self.waiting_reason})"
        )
