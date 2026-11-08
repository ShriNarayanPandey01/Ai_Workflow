from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ai_workflow.contracts.common.types import JsonValue

if TYPE_CHECKING:
    from ai_workflow.security.credentials import CredentialResolver


class TransientNodeError(Exception):
    """Raised by a node executor to signal a transient, retryable failure.

    The runner retries a node that raises this (up to the workflow's
    ``ExecutionPolicy.default_retry`` limit) with exponential backoff. Any
    other exception is treated as terminal and fails the run immediately.
    """


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable per-node execution context passed to node executors."""

    run_id: UUID
    workspace_id: UUID
    project_id: UUID
    workflow_version_id: UUID | None
    node_id: UUID
    attempt: int
    deadline: datetime | None = None
    idempotency_key: str | None = None
    runtime: dict[str, JsonValue] = field(default_factory=dict)
    input_schema: dict[str, JsonValue] = field(default_factory=dict)
    output_schema: dict[str, JsonValue] = field(default_factory=dict)
    credential_refs: dict[str, UUID] = field(default_factory=dict)
    resource_refs: dict[str, UUID] = field(default_factory=dict)
    credential_resolver: CredentialResolver | None = None
    cancel_check: Callable[[], bool] | None = None


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Output port values produced by a single node execution."""

    outputs: dict[str, JsonValue] = field(default_factory=dict)


class NodeExecutor(Protocol):
    """Contract implemented by every workflow node executor."""

    node_type: str

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult: ...


class UnimplementedNodeExecutor:
    """Placeholder executor for catalogued-but-unbuilt inline node types.

    Some inline node types ship in the contracts catalog before their executor
    is implemented (e.g. the F16 ``market.*`` domain nodes). Registering this
    placeholder lets the runtime run with ``strict_catalog=True`` — so the
    registry still refuses to start if a genuinely in-scope node is missing an
    executor — while any attempt to actually execute an unbuilt node fails
    loudly with a clear message instead of a bare ``KeyError`` lookup miss.
    """

    def __init__(self, node_type: str) -> None:
        """Bind the placeholder to the catalog node type it stands in for."""
        self.node_type = node_type

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        """Fail loudly: this node type is catalogued but not yet implemented."""
        msg = f"Node type {self.node_type} is not implemented in this engine build"
        raise NotImplementedError(msg)
