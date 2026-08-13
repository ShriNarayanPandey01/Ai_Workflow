from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workflow.runtime.condition import (
    ConditionEvaluationError,
    evaluate_condition,
)


@pytest.fixture
def nested_condition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "condition-nested.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_nested_condition_fixture_true(nested_condition: dict) -> None:
    state = {
        "score": 0.9,
        "status": "ready",
        "tags": ["priority", "ops"],
        "customer_id": "c-1",
    }
    assert evaluate_condition(nested_condition, state) is True


def test_nested_condition_fixture_false_when_score_low(nested_condition: dict) -> None:
    state = {
        "score": 0.1,
        "status": "ready",
        "tags": ["priority"],
        "customer_id": "c-1",
    }
    assert evaluate_condition(nested_condition, state) is False


def test_missing_path_is_falsy_not_exception() -> None:
    expr = {
        "op": "eq",
        "left": {"kind": "path", "value": "/missing"},
        "right": {"kind": "literal", "value": 1},
    }
    assert evaluate_condition(expr, {}) is False


def test_exists_and_is_null() -> None:
    state = {"a": None, "b": 1}
    assert (
        evaluate_condition(
            {"op": "exists", "value": {"kind": "path", "value": "/b"}},
            state,
        )
        is True
    )
    assert (
        evaluate_condition(
            {"op": "exists", "value": {"kind": "path", "value": "/missing"}},
            state,
        )
        is False
    )
    assert (
        evaluate_condition(
            {"op": "isNull", "value": {"kind": "path", "value": "/a"}},
            state,
        )
        is True
    )


def test_string_ops() -> None:
    state = {"name": "workflow-engine"}
    assert evaluate_condition(
        {
            "op": "startsWith",
            "left": {"kind": "path", "value": "/name"},
            "right": {"kind": "literal", "value": "work"},
        },
        state,
    )
    assert evaluate_condition(
        {
            "op": "endsWith",
            "left": {"kind": "path", "value": "/name"},
            "right": {"kind": "literal", "value": "engine"},
        },
        state,
    )
    assert evaluate_condition(
        {
            "op": "contains",
            "left": {"kind": "path", "value": "/name"},
            "right": {"kind": "literal", "value": "flow"},
        },
        state,
    )


def test_unknown_operator_raises() -> None:
    with pytest.raises(ConditionEvaluationError, match="Unknown condition operator"):
        evaluate_condition({"op": "eval", "left": {"kind": "literal", "value": 1}}, {})


def test_max_depth_enforced() -> None:
    expr: dict = {
        "op": "not",
        "arg": {
            "op": "eq",
            "left": {"kind": "literal", "value": 1},
            "right": {"kind": "literal", "value": 1},
        },
    }
    # nest beyond depth 2
    for _ in range(5):
        expr = {"op": "not", "arg": expr}
    with pytest.raises(ConditionEvaluationError, match="maximum depth"):
        evaluate_condition(expr, {}, max_depth=2)


def test_none_expression_is_false() -> None:
    assert evaluate_condition(None, {}) is False
