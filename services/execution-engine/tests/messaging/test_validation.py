from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workflow.messaging.validation import (
    EnvelopeValidationError,
    validate_envelope_document,
)


def test_validate_execution_start_fixture(repo_contracts_root: Path) -> None:
    fixture_path = (
        repo_contracts_root / "fixtures" / "valid" / "envelope-execution-start.json"
    )
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    validate_envelope_document(document, contracts_root=repo_contracts_root)


def test_validate_rejects_command_with_sequence(
    repo_contracts_root: Path,
    workflow_linear_definition: dict,
) -> None:
    document = {
        "message_id": str(uuid4()),
        "message_type": "execution.start",
        "schema_version": "1.0",
        "occurred_at": "2026-07-24T12:45:00Z",
        "correlation_id": str(uuid4()),
        "causation_id": None,
        "idempotency_key": "start:test",
        "tenant": {
            "workspace_id": str(uuid4()),
            "project_id": str(uuid4()),
        },
        "subject": {
            "workflow_id": str(uuid4()),
            "workflow_version_id": str(uuid4()),
            "run_id": str(uuid4()),
            "node_id": None,
            "task_id": None,
            "document_id": None,
        },
        "sequence": 1,
        "payload": {
            "mode": "published",
            "draft_revision": None,
            "input": {"order_id": "x"},
            "definition": workflow_linear_definition,
        },
    }
    with pytest.raises(EnvelopeValidationError):
        validate_envelope_document(document, contracts_root=repo_contracts_root)
