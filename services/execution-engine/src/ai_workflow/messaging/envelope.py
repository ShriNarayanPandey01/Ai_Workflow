from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ai_workflow.contracts.common.types import JsonValue


class Tenant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    project_id: UUID


class ExecutionSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    workflow_version_id: UUID | None = None
    run_id: UUID
    node_id: UUID | None = None
    task_id: UUID | None = None
    document_id: UUID | None = None


class ExecutionStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    definition: dict[str, JsonValue]
    input: dict[str, JsonValue]
    draft_revision: int | None = None
    trigger: dict[str, JsonValue] | None = None


class ExecutionResumePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waiting_reason: str
    interrupt_id: UUID
    approval_id: UUID | None = None
    task_id: UUID | None = None
    decision: JsonValue


class ExecutionCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    requested_by: UUID | None = None


class MessageEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    message_type: str
    schema_version: str
    occurred_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    idempotency_key: str
    tenant: Tenant
    subject: dict[str, Any]
    sequence: int | None
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ParsedExecutionStart:
    envelope: MessageEnvelope
    payload: ExecutionStartPayload
    subject: ExecutionSubject


@dataclass(frozen=True, slots=True)
class ParsedExecutionResume:
    envelope: MessageEnvelope
    payload: ExecutionResumePayload
    subject: ExecutionSubject


@dataclass(frozen=True, slots=True)
class ParsedExecutionCancel:
    envelope: MessageEnvelope
    payload: ExecutionCancelPayload
    subject: ExecutionSubject


def parse_execution_start(data: dict[str, Any]) -> ParsedExecutionStart:
    """Validate and parse an execution.start command envelope."""
    envelope = MessageEnvelope.model_validate(data)
    payload = ExecutionStartPayload.model_validate(envelope.payload)
    subject = ExecutionSubject.model_validate(envelope.subject)
    return ParsedExecutionStart(envelope=envelope, payload=payload, subject=subject)


def parse_execution_resume(data: dict[str, Any]) -> ParsedExecutionResume:
    """Validate and parse an execution.resume command envelope."""
    envelope = MessageEnvelope.model_validate(data)
    payload = ExecutionResumePayload.model_validate(envelope.payload)
    subject = ExecutionSubject.model_validate(envelope.subject)
    return ParsedExecutionResume(envelope=envelope, payload=payload, subject=subject)


def parse_execution_cancel(data: dict[str, Any]) -> ParsedExecutionCancel:
    """Validate and parse an execution.cancel command envelope."""
    envelope = MessageEnvelope.model_validate(data)
    payload = ExecutionCancelPayload.model_validate(envelope.payload)
    subject = ExecutionSubject.model_validate(envelope.subject)
    return ParsedExecutionCancel(envelope=envelope, payload=payload, subject=subject)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_event_envelope(
    *,
    message_id: UUID,
    message_type: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    idempotency_key: str,
    tenant: Tenant,
    subject: dict[str, Any],
    sequence: int | None,
    payload: dict[str, JsonValue],
) -> dict[str, Any]:
    """Build a contract-compliant outbound event envelope dict."""
    return {
        "message_id": str(message_id),
        "message_type": message_type,
        "schema_version": "1.0",
        "occurred_at": utc_now_iso(),
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id) if causation_id else None,
        "idempotency_key": idempotency_key,
        "tenant": tenant.model_dump(mode="json"),
        "subject": subject,
        "sequence": sequence,
        "payload": payload,
    }
