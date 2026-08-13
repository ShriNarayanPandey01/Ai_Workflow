from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from ai_workflow.contracts.common.types import JsonValue

_DEFINITION_SCHEMA: dict | None = None
_VALIDATOR: Draft202012Validator | None = None
_VALIDATOR_ROOT: Path | None = None

WORKFLOW_SCHEMA_ID = "https://ai-workflow.local/contracts/workflow/definition.schema.json"
CONDITION_SCHEMA_ID = "https://ai-workflow.local/contracts/workflow/condition.schema.json"


class WorkflowValidationError(Exception):
    """Raised when a workflow definition fails JSON Schema validation."""


class NodePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int
    multiplier: float
    jitter: bool = True


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int
    max_node_executions: int
    max_parallel_nodes: int
    max_fan_out_items: int
    max_task_seconds: int
    max_provider_calls: int
    max_artifact_bytes: int
    max_estimated_cost: float | None = None
    default_retry: RetryPolicy


class InputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_port: str
    target_path: str
    source_node_id: UUID
    source_port: str
    source_path: str
    origin: Literal["user", "default", "pass_through"]


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: str
    position: NodePosition
    config: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] | None = None
    credential_refs: dict[str, UUID] = Field(default_factory=dict)
    resource_refs: dict[str, UUID] = Field(default_factory=dict)
    input_bindings: list[InputBinding] | None = None


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_node_id: UUID
    source_port: str
    target_node_id: UUID
    target_port: str
    label: str | None = None
    condition: dict[str, JsonValue] | None = None


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    workflow_id: UUID
    workflow_version_id: UUID | None = None
    name: str
    metadata: dict[str, JsonValue] | None = None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    execution_policy: ExecutionPolicy

    def node_by_id(self) -> dict[str, WorkflowNode]:
        return {str(node.id): node for node in self.nodes}

    def incoming_edges(self, node_id: UUID) -> list[WorkflowEdge]:
        node_key = str(node_id)
        return [edge for edge in self.edges if str(edge.target_node_id) == node_key]


def _definition_schema_path(contracts_root: Path) -> Path:
    """Return the path to the workflow definition JSON Schema file."""
    return contracts_root / "workflow" / "definition.schema.json"


def load_definition_schema(contracts_root: Path) -> dict:
    """Load and cache the workflow definition JSON Schema and its registry."""
    global _DEFINITION_SCHEMA, _VALIDATOR, _VALIDATOR_ROOT
    if _DEFINITION_SCHEMA is None or _VALIDATOR_ROOT != contracts_root:
        workflow_dir = contracts_root / "workflow"
        definition: dict = json.loads(
            _definition_schema_path(contracts_root).read_text(encoding="utf-8")
        )
        condition: dict = json.loads(
            (workflow_dir / "condition.schema.json").read_text(encoding="utf-8")
        )
        registry = Registry().with_resources(
            [
                (WORKFLOW_SCHEMA_ID, DRAFT202012.create_resource(definition)),
                (CONDITION_SCHEMA_ID, DRAFT202012.create_resource(condition)),
            ]
        )
        _DEFINITION_SCHEMA = definition
        _VALIDATOR = Draft202012Validator(definition, registry=registry)
        _VALIDATOR_ROOT = contracts_root
    return _DEFINITION_SCHEMA


def _get_validator(contracts_root: Path) -> Draft202012Validator:
    """Return a cached Draft 2020-12 validator for workflow definition documents."""
    load_definition_schema(contracts_root)
    assert _VALIDATOR is not None
    return _VALIDATOR


def validate_definition_document(
    document: dict,
    *,
    contracts_root: Path,
    source: str = "<unknown>",
) -> None:
    """Validate a workflow definition document against the contracts schema."""
    validator = _get_validator(contracts_root)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise WorkflowValidationError(f"{source}: {location}: {first.message}")


def workflow_from_dict(data: dict[str, JsonValue]) -> WorkflowDefinition:
    """Parse and validate a workflow definition dict into a ``WorkflowDefinition``."""
    return WorkflowDefinition.model_validate(data)


def load_workflow_definition(
    path: Path,
    *,
    contracts_root: Path,
) -> WorkflowDefinition:
    """Load a workflow JSON file, validate it, and return a parsed definition."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_definition_document(raw, contracts_root=contracts_root, source=path.name)
    return workflow_from_dict(raw)


def reset_definition_schema_cache() -> None:
    """Clear cached workflow definition schema and validator state (for tests)."""
    global _DEFINITION_SCHEMA, _VALIDATOR, _VALIDATOR_ROOT
    _DEFINITION_SCHEMA = None
    _VALIDATOR = None
    _VALIDATOR_ROOT = None
