from __future__ import annotations

import re

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult

_VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class PromptTemplateNodeExecutor:
    node_type = "ai.prompt-template@1"

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        del context
        template = config.get("template")
        if not isinstance(template, str) or not template:
            msg = "ai.prompt-template@1 requires a non-empty template"
            raise ValueError(msg)

        variables = inputs.get("variables")
        if not isinstance(variables, dict):
            msg = "ai.prompt-template@1 requires object input port 'variables'"
            raise ValueError(msg)

        required = config.get("required_variables") or []
        if not isinstance(required, list):
            msg = "required_variables must be an array of strings"
            raise ValueError(msg)

        missing = [name for name in required if not isinstance(name, str) or name not in variables]
        if missing:
            msg = f"Missing required template variables: {', '.join(str(m) for m in missing)}"
            raise ValueError(msg)

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                return ""
            value = variables[name]
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                msg = f"Template variable {name!r} must be a scalar"
                raise ValueError(msg)
            return str(value)

        rendered = _VAR_PATTERN.sub(replace, template)
        return NodeResult(outputs={"text": {"text": rendered}})
