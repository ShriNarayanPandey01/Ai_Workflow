from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from ai_workflow.contracts.common.types import JsonValue

ENVELOPE_SCHEMA_ID = "https://ai-workflow.local/contracts/messages/envelope.schema.json"


class EnvelopeValidationError(Exception):
    """Raised when a message envelope fails JSON Schema validation."""


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

    @classmethod
    def event_dict(
        _cls,
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


@dataclass(frozen=True, slots=True)
class ParsedExecutionStart:
    envelope: MessageEnvelope
    payload: ExecutionStartPayload
    subject: ExecutionSubject

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> ParsedExecutionStart:
        envelope = MessageEnvelope.model_validate(data)
        payload = ExecutionStartPayload.model_validate(envelope.payload)
        subject = ExecutionSubject.model_validate(envelope.subject)
        return cls(envelope=envelope, payload=payload, subject=subject)


@dataclass(frozen=True, slots=True)
class ParsedExecutionResume:
    envelope: MessageEnvelope
    payload: ExecutionResumePayload
    subject: ExecutionSubject

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> ParsedExecutionResume:
        envelope = MessageEnvelope.model_validate(data)
        payload = ExecutionResumePayload.model_validate(envelope.payload)
        subject = ExecutionSubject.model_validate(envelope.subject)
        return cls(envelope=envelope, payload=payload, subject=subject)


@dataclass(frozen=True, slots=True)
class ParsedExecutionCancel:
    envelope: MessageEnvelope
    payload: ExecutionCancelPayload
    subject: ExecutionSubject

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> ParsedExecutionCancel:
        envelope = MessageEnvelope.model_validate(data)
        payload = ExecutionCancelPayload.model_validate(envelope.payload)
        subject = ExecutionSubject.model_validate(envelope.subject)
        return cls(envelope=envelope, payload=payload, subject=subject)


class EnvelopeValidator:
    """Validates message envelopes against the contracts JSON Schema."""

    def __init__(self, contracts_root: Path) -> None:
        self._contracts_root = contracts_root
        self._validator = self._load()

    def validate(self, document: dict, *, source: str = "<unknown>") -> None:
        errors = sorted(
            self._validator.iter_errors(document),
            key=lambda error: list(error.path),
        )
        if errors:
            first = errors[0]
            location = "/".join(str(part) for part in first.path) or "<root>"
            raise EnvelopeValidationError(f"{source}: {location}: {first.message}")

    def _load(self) -> Draft202012Validator:
        envelope_path = self._contracts_root / "messages" / "envelope.schema.json"
        if not envelope_path.is_file():
            msg = f"Envelope schema not found: {envelope_path}"
            raise EnvelopeValidationError(msg)

        _, envelope_schema = self._load_schema_file(envelope_path)
        registry = self._build_registry(self._contracts_root)
        return Draft202012Validator(envelope_schema, registry=registry)

    @staticmethod
    def _load_schema_file(path: Path) -> tuple[str, dict]:
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            msg = f"Schema file missing $id: {path}"
            raise EnvelopeValidationError(msg)
        return schema_id, schema

    @classmethod
    def _build_registry(cls, contracts_root: Path) -> Registry:
        resources: list[tuple[str, Any]] = []
        for schema_path in sorted(contracts_root.rglob("*.schema.json")):
            schema_id, schema = cls._load_schema_file(schema_path)
            resources.append((schema_id, DRAFT202012.create_resource(schema)))
        return Registry().with_resources(resources)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
