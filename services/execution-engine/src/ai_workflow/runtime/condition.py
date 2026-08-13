from __future__ import annotations

from typing import Any

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.runtime.bindings import json_pointer_get

DEFAULT_MAX_DEPTH = 10

_COMPARISON_OPS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte"})
_STRING_OPS = frozenset({"contains", "startsWith", "endsWith"})
_UNARY_OPS = frozenset({"exists", "isNull"})
_GROUP_OPS = frozenset({"all", "any"})


class ConditionEvaluationError(ValueError):
    """Raised when a condition AST is malformed or exceeds limits."""


def evaluate_condition(
    expression: dict[str, Any] | None,
    state_root: dict[str, JsonValue],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> bool:
    """Evaluate a ConditionExpression AST against a workflow state root.

    Missing paths do not raise: ``exists`` is False and comparisons involving
    missing paths evaluate to False.
    """
    if expression is None:
        return False
    return _eval(expression, state_root, depth=0, max_depth=max_depth)


def _eval(
    expression: dict[str, Any],
    state_root: dict[str, JsonValue],
    *,
    depth: int,
    max_depth: int,
) -> bool:
    """Recursively evaluate one condition expression node."""
    if depth > max_depth:
        msg = f"Condition expression exceeds maximum depth of {max_depth}"
        raise ConditionEvaluationError(msg)

    if not isinstance(expression, dict) or "op" not in expression:
        msg = "Condition expression must be an object with an 'op' field"
        raise ConditionEvaluationError(msg)

    op = expression["op"]
    if not isinstance(op, str):
        msg = "Condition operator must be a string"
        raise ConditionEvaluationError(msg)

    if op in _GROUP_OPS:
        args = expression.get("args")
        if not isinstance(args, list) or not (1 <= len(args) <= 20):
            msg = f"Operator {op!r} requires 1..20 args"
            raise ConditionEvaluationError(msg)
        results = [
            _eval(arg, state_root, depth=depth + 1, max_depth=max_depth)
            for arg in args
        ]
        return all(results) if op == "all" else any(results)

    if op == "not":
        arg = expression.get("arg")
        if not isinstance(arg, dict):
            msg = "Operator 'not' requires an 'arg' expression"
            raise ConditionEvaluationError(msg)
        return not _eval(arg, state_root, depth=depth + 1, max_depth=max_depth)

    if op in _UNARY_OPS:
        operand = expression.get("value")
        if not isinstance(operand, dict):
            msg = f"Operator {op!r} requires a 'value' operand"
            raise ConditionEvaluationError(msg)
        if op == "exists":
            return _operand_exists(operand, state_root)
        resolved = _resolve_operand(operand, state_root, missing_ok=True)
        return resolved is None

    if op in _COMPARISON_OPS | _STRING_OPS:
        left_op = expression.get("left")
        right_op = expression.get("right")
        if not isinstance(left_op, dict) or not isinstance(right_op, dict):
            msg = f"Operator {op!r} requires 'left' and 'right' operands"
            raise ConditionEvaluationError(msg)

        left_missing = not _operand_exists(left_op, state_root)
        right_missing = not _operand_exists(right_op, state_root)
        if left_missing or right_missing:
            return False

        left = _resolve_operand(left_op, state_root, missing_ok=False)
        right = _resolve_operand(right_op, state_root, missing_ok=False)
        return _compare(op, left, right)

    msg = f"Unknown condition operator: {op!r}"
    raise ConditionEvaluationError(msg)


def _operand_exists(operand: dict[str, Any], state_root: dict[str, JsonValue]) -> bool:
    """Return whether a literal or path operand can be resolved."""
    kind = operand.get("kind")
    if kind == "literal":
        return "value" in operand
    if kind == "path":
        path = operand.get("value")
        if not isinstance(path, str):
            return False
        try:
            json_pointer_get(state_root, path)
        except (KeyError, ValueError, TypeError):
            return False
        return True
    return False


def _resolve_operand(
    operand: dict[str, Any],
    state_root: dict[str, JsonValue],
    *,
    missing_ok: bool,
) -> JsonValue:
    """Resolve a literal or path operand to its runtime value."""
    kind = operand.get("kind")
    if kind == "literal":
        return operand.get("value")  # type: ignore[return-value]
    if kind == "path":
        path = operand.get("value")
        if not isinstance(path, str):
            msg = "Path operand value must be a string"
            raise ConditionEvaluationError(msg)
        try:
            return json_pointer_get(state_root, path)
        except (KeyError, ValueError, TypeError):
            if missing_ok:
                return None
            raise
    msg = f"Unknown operand kind: {kind!r}"
    raise ConditionEvaluationError(msg)


def _compare(op: str, left: JsonValue, right: JsonValue) -> bool:
    """Apply a comparison or string operator to two resolved values."""
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right

    if op == "contains":
        if isinstance(left, str) and isinstance(right, str):
            return right in left
        if isinstance(left, list):
            return right in left
        return False

    if op in {"startsWith", "endsWith"}:
        if not isinstance(left, str) or not isinstance(right, str):
            return False
        if op == "startsWith":
            return left.startswith(right)
        return left.endswith(right)

    if op in {"gt", "gte", "lt", "lte"}:
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if op == "gt":
                return left > right
            if op == "gte":
                return left >= right
            if op == "lt":
                return left < right
            return left <= right
        if isinstance(left, str) and isinstance(right, str):
            if op == "gt":
                return left > right
            if op == "gte":
                return left >= right
            if op == "lt":
                return left < right
            return left <= right
        return False

    return False
