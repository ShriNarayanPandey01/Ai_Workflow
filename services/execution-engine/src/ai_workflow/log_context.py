from __future__ import annotations

from typing import Any
from uuid import UUID


def execution_log_extra(
    *,
    role: str,
    run_id: UUID | str | None = None,
    correlation_id: UUID | str | None = None,
    node_id: UUID | str | None = None,
    message_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Structured fields required on execution-engine worker logs."""
    extra: dict[str, Any] = {"worker_role": role}
    if run_id is not None:
        extra["run_id"] = str(run_id)
    if correlation_id is not None:
        extra["correlation_id"] = str(correlation_id)
    if node_id is not None:
        extra["node_id"] = str(node_id)
    if message_id is not None:
        extra["message_id"] = str(message_id)
    return extra
