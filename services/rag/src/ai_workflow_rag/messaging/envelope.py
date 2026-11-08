from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Tenant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    project_id: UUID


class DocumentSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID


class DocumentIngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: UUID
    document_id: UUID
    object_key: str
    content_hash: str
    media_type: str
    size_bytes: int
    version: int
    original_name: str | None = None
    embedding_config: dict[str, Any] = Field(default_factory=dict)


class DocumentDeletePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: UUID
    document_id: UUID
    delete_object: bool = True
    delete_vectors: bool = True


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
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedDocumentIngest:
    envelope: MessageEnvelope
    payload: DocumentIngestPayload
    subject: DocumentSubject


@dataclass(frozen=True, slots=True)
class ParsedDocumentDelete:
    envelope: MessageEnvelope
    payload: DocumentDeletePayload
    subject: DocumentSubject


def parse_document_ingest(data: dict[str, Any]) -> ParsedDocumentIngest:
    envelope = MessageEnvelope.model_validate(data)
    payload = DocumentIngestPayload.model_validate(envelope.payload)
    subject = DocumentSubject.model_validate(envelope.subject)
    return ParsedDocumentIngest(envelope=envelope, payload=payload, subject=subject)


def parse_document_delete(data: dict[str, Any]) -> ParsedDocumentDelete:
    envelope = MessageEnvelope.model_validate(data)
    payload = DocumentDeletePayload.model_validate(envelope.payload)
    subject = DocumentSubject.model_validate(envelope.subject)
    return ParsedDocumentDelete(envelope=envelope, payload=payload, subject=subject)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_document_event_envelope(
    *,
    message_id: UUID,
    message_type: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    idempotency_key: str,
    tenant: Tenant,
    document_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "message_id": str(message_id),
        "message_type": message_type,
        "schema_version": "1.0",
        "occurred_at": utc_now_iso(),
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id) if causation_id else None,
        "idempotency_key": idempotency_key,
        "tenant": tenant.model_dump(mode="json"),
        "subject": {"document_id": str(document_id)},
        "sequence": None,
        "payload": payload,
    }
