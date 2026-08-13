from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult


class InputNodeExecutor:
    node_type = "data.input@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        del config, inputs
        run_input = context.runtime.get("run_input")
        if run_input is None:
            msg = "Missing run_input in workflow runtime"
            raise ValueError(msg)

        _validate_schema(run_input, context.input_schema, label="workflow input")
        return NodeResult(outputs={"value": run_input})


def _validate_schema(value: JsonValue, schema: dict[str, Any], *, label: str) -> None:
    """Validate a JSON value against a JSON Schema, raising ``ValueError`` on failure."""
    if not schema:
        return
    validator = Draft202012Validator(schema)
    try:
        validator.validate(value)
    except ValidationError as exc:
        msg = f"Invalid {label}: {exc.message}"
        raise ValueError(msg) from exc
