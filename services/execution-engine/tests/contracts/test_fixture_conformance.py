"""F2 contract-conformance harness.

Exercises every shared fixture under ``contracts/fixtures/`` against the Python
validators so the "contracts are the source of truth" promise is actually
demonstrated:

* every ``valid/*`` file is accepted by its validator (JSON Schema, plus
  semantic validation for workflow definitions);
* every ``invalid/*`` file is rejected at the layer its ``.meta.json`` declares,
  and — for the semantic layer, where stable error codes exist — the emitted
  codes match the expected ``error_codes``.

JSON-Schema-layer rejections (envelope / condition / ``additionalProperties``)
currently surface only free-text messages, so those cases assert rejection but
not a specific code; the semantic validator is the only source of stable codes
today, and those are asserted precisely.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_workflow.config.settings import REPO_ROOT
from ai_workflow.contracts.nodes.catalog_loader import (
    ManifestValidationError,
    validate_manifest_document,
)
from ai_workflow.contracts.workflow.definition import (
    WorkflowValidationError,
    validate_definition_document,
    workflow_from_dict,
)
from ai_workflow.messaging.envelope import EnvelopeValidationError, EnvelopeValidator
from ai_workflow.runtime.semantics.validator import (
    SemanticValidationError,
    validate_workflow_semantics,
)

CONTRACTS_ROOT = REPO_ROOT / "contracts"
FIXTURES_ROOT = CONTRACTS_ROOT / "fixtures"
VALID_DIR = FIXTURES_ROOT / "valid"
INVALID_DIR = FIXTURES_ROOT / "invalid"

_CONDITION_SCHEMA = json.loads(
    (CONTRACTS_ROOT / "workflow" / "condition.schema.json").read_text(encoding="utf-8")
)
_CONDITION_VALIDATOR = Draft202012Validator(_CONDITION_SCHEMA)


def _fixture_files(directory: Path) -> list[Path]:
    """Return fixture JSON files in a directory, excluding ``*.meta.json`` sidecars."""
    return sorted(
        path
        for path in directory.glob("*.json")
        if not path.name.endswith(".meta.json")
    )


def _load_meta(fixture_path: Path) -> dict:
    """Load the ``.meta.json`` sidecar for a fixture, or ``{}`` if none exists."""
    meta_path = fixture_path.parent / f"{fixture_path.stem}.meta.json"
    if not meta_path.is_file():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _route(fixture_path: Path, meta: dict) -> str:
    """Pick the validator for a fixture from its meta ``schema`` or file name."""
    schema = str(meta.get("schema", ""))
    name = fixture_path.name
    if "envelope" in schema or name.startswith("envelope-"):
        return "envelope"
    if "condition" in schema or name.startswith("condition-"):
        return "condition"
    if "manifest" in schema or name.startswith("manifest-"):
        return "manifest"
    return "workflow"


def _validate_condition(document: object) -> None:
    """Validate a bare condition-AST document against the condition schema."""
    errors = sorted(
        _CONDITION_VALIDATOR.iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise WorkflowValidationError(errors[0].message)


@pytest.mark.parametrize("fixture_path", _fixture_files(VALID_DIR), ids=lambda p: p.name)
def test_valid_fixture_accepted(fixture_path: Path) -> None:
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    kind = _route(fixture_path, _load_meta(fixture_path))

    if kind == "envelope":
        EnvelopeValidator(CONTRACTS_ROOT).validate(document, source=fixture_path.name)
    elif kind == "condition":
        _validate_condition(document)
    elif kind == "manifest":
        validate_manifest_document(
            document, contracts_root=CONTRACTS_ROOT, source=fixture_path.name
        )
    else:
        validate_definition_document(
            document, contracts_root=CONTRACTS_ROOT, source=fixture_path.name
        )
        definition = workflow_from_dict(document)
        validate_workflow_semantics(definition, contracts_root=CONTRACTS_ROOT)


@pytest.mark.parametrize("fixture_path", _fixture_files(INVALID_DIR), ids=lambda p: p.name)
def test_invalid_fixture_rejected(fixture_path: Path) -> None:
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    meta = _load_meta(fixture_path)
    expects = meta.get("expects")
    if expects is None:
        # Fixtures without a static-validation ``expects`` block (e.g. runtime
        # cap violations) are covered by the runner tests, not the validators.
        pytest.skip(f"{fixture_path.name}: no static-validation expectations")

    kind = _route(fixture_path, meta)
    expected_codes = set(expects.get("error_codes", []))

    if kind == "envelope":
        with pytest.raises(EnvelopeValidationError):
            EnvelopeValidator(CONTRACTS_ROOT).validate(
                document, source=fixture_path.name
            )
        return

    if kind == "condition":
        with pytest.raises(WorkflowValidationError):
            _validate_condition(document)
        return

    if kind == "manifest":
        with pytest.raises(ManifestValidationError):
            validate_manifest_document(
                document, contracts_root=CONTRACTS_ROOT, source=fixture_path.name
            )
        return

    # Workflow-definition fixture.
    if not expects.get("json_schema_valid", False):
        # Rejected at the JSON-Schema structural layer (free-text message only).
        with pytest.raises(WorkflowValidationError):
            validate_definition_document(
                document, contracts_root=CONTRACTS_ROOT, source=fixture_path.name
            )
        return

    # Structurally valid, must be rejected by semantic validation with a code
    # from the fixture's declared set.
    validate_definition_document(
        document, contracts_root=CONTRACTS_ROOT, source=fixture_path.name
    )
    definition = workflow_from_dict(document)
    with pytest.raises(SemanticValidationError) as exc_info:
        validate_workflow_semantics(definition, contracts_root=CONTRACTS_ROOT)

    if expected_codes:
        emitted = {error.code for error in exc_info.value.errors}
        assert emitted & expected_codes, (
            f"{fixture_path.name}: expected one of {sorted(expected_codes)}, "
            f"got {sorted(emitted)}"
        )
