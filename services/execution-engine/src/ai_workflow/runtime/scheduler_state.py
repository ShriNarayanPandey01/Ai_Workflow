from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.runtime.state import WorkflowState

SCHEDULER_KEY = "_scheduler"
INTERRUPT_KEY = "_interrupt"
DEFINITION_KEY = "_definition"


@dataclass
class SchedulerSnapshot:
    """Serializable scheduler state persisted inside a workflow checkpoint."""

    produced: set[tuple[str, str]] = field(default_factory=set)
    production_order: dict[tuple[str, str], int] = field(default_factory=dict)
    production_seq: int = 0
    executed_output_ids: set[str] = field(default_factory=set)
    node_executions: int = 0
    pending: deque[str] = field(default_factory=deque)
    in_pending: set[str] = field(default_factory=set)


def save_scheduler(state: WorkflowState, scheduler: SchedulerSnapshot) -> None:
    """Persist scheduler progress into workflow runtime state."""
    state.runtime[SCHEDULER_KEY] = {
        "produced": [[node_id, port] for node_id, port in sorted(scheduler.produced)],
        "production_order": {
            f"{node_id}:{port}": seq
            for (node_id, port), seq in scheduler.production_order.items()
        },
        "production_seq": scheduler.production_seq,
        "executed_output_ids": sorted(scheduler.executed_output_ids),
        "node_executions": scheduler.node_executions,
        "pending": list(scheduler.pending),
        "in_pending": sorted(scheduler.in_pending),
    }


def load_scheduler(state: WorkflowState) -> SchedulerSnapshot | None:
    """Restore scheduler progress from workflow runtime state."""
    raw = state.runtime.get(SCHEDULER_KEY)
    if not isinstance(raw, dict):
        return None
    produced_raw = raw.get("produced", [])
    produced: set[tuple[str, str]] = set()
    if isinstance(produced_raw, list):
        for item in produced_raw:
            if isinstance(item, list) and len(item) == 2:
                produced.add((str(item[0]), str(item[1])))

    production_order: dict[tuple[str, str], int] = {}
    order_raw = raw.get("production_order", {})
    if isinstance(order_raw, dict):
        for key, seq in order_raw.items():
            if isinstance(key, str) and ":" in key and isinstance(seq, int):
                node_id, port = key.split(":", 1)
                production_order[(node_id, port)] = seq

    pending_raw = raw.get("pending", [])
    pending: deque[str] = deque()
    if isinstance(pending_raw, list):
        pending.extend(str(item) for item in pending_raw)

    in_pending_raw = raw.get("in_pending", [])
    in_pending: set[str] = set()
    if isinstance(in_pending_raw, list):
        in_pending.update(str(item) for item in in_pending_raw)

    executed_raw = raw.get("executed_output_ids", [])
    executed: set[str] = set()
    if isinstance(executed_raw, list):
        executed.update(str(item) for item in executed_raw)

    production_seq = raw.get("production_seq", 0)
    node_executions = raw.get("node_executions", 0)

    return SchedulerSnapshot(
        produced=produced,
        production_order=production_order,
        production_seq=int(production_seq) if isinstance(production_seq, int) else 0,
        executed_output_ids=executed,
        node_executions=int(node_executions) if isinstance(node_executions, int) else 0,
        pending=pending,
        in_pending=in_pending,
    )


def save_interrupt(
    state: WorkflowState,
    *,
    interrupt_id: str,
    waiting_reason: str,
    node_id: str,
    approval_id: str | None,
    node_type: str,
    approval_request: dict[str, JsonValue],
    task_id: str | None = None,
) -> None:
    """Record the interrupt metadata needed to resume a waiting workflow."""
    state.runtime[INTERRUPT_KEY] = {
        "interrupt_id": interrupt_id,
        "waiting_reason": waiting_reason,
        "node_id": node_id,
        "approval_id": approval_id,
        "node_type": node_type,
        "approval_request": approval_request,
        "task_id": task_id,
    }


def get_interrupt(state: WorkflowState) -> dict[str, Any] | None:
    """Return interrupt metadata when a run is waiting for external input."""
    raw = state.runtime.get(INTERRUPT_KEY)
    return raw if isinstance(raw, dict) else None


def clear_interrupt(state: WorkflowState) -> None:
    """Remove interrupt metadata after a resume decision is applied."""
    state.runtime.pop(INTERRUPT_KEY, None)
