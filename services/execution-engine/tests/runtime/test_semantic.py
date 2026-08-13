from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workflow.contracts.workflow.definition import workflow_from_dict
from ai_workflow.runtime.semantic import SemanticValidationError, validate_workflow_semantics


def test_arbitrary_cycle_rejected(repo_contracts_root: Path) -> None:
    path = repo_contracts_root / "fixtures" / "invalid" / "workflow-arbitrary-cycle.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    definition = workflow_from_dict(raw)

    with pytest.raises(SemanticValidationError) as exc_info:
        validate_workflow_semantics(definition, contracts_root=repo_contracts_root)

    codes = {error.code for error in exc_info.value.errors}
    assert "ARBITRARY_CYCLE" in codes


def test_unbounded_loop_rejected(repo_contracts_root: Path) -> None:
    path = repo_contracts_root / "fixtures" / "invalid" / "workflow-unbounded-loop.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    definition = workflow_from_dict(raw)

    with pytest.raises(SemanticValidationError) as exc_info:
        validate_workflow_semantics(definition, contracts_root=repo_contracts_root)

    codes = {error.code for error in exc_info.value.errors}
    assert "LOOP_UNBOUNDED" in codes or "NODE_CONFIG_INVALID" in codes


def test_bounded_loop_fixture_passes_semantics(repo_contracts_root: Path) -> None:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-bounded-loop.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    definition = workflow_from_dict(raw)
    validate_workflow_semantics(definition, contracts_root=repo_contracts_root)


def test_field_bindings_fixture_passes_semantics(repo_contracts_root: Path) -> None:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-field-bindings.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    definition = workflow_from_dict(raw)
    validate_workflow_semantics(definition, contracts_root=repo_contracts_root)


@pytest.mark.parametrize(
    ("fixture_name", "expected_code"),
    [
        ("workflow-binding-missing.json", "BINDING_MISSING"),
        ("workflow-binding-unreachable.json", "BINDING_UNREACHABLE"),
        ("workflow-binding-incompatible.json", "BINDING_INCOMPATIBLE"),
        ("workflow-binding-ambiguous.json", "BINDING_AMBIGUOUS"),
    ],
)
def test_binding_fixtures_rejected(
    repo_contracts_root: Path,
    fixture_name: str,
    expected_code: str,
) -> None:
    path = repo_contracts_root / "fixtures" / "invalid" / fixture_name
    raw = json.loads(path.read_text(encoding="utf-8"))
    definition = workflow_from_dict(raw)

    with pytest.raises(SemanticValidationError) as exc_info:
        validate_workflow_semantics(definition, contracts_root=repo_contracts_root)

    codes = {error.code for error in exc_info.value.errors}
    assert expected_code in codes
