from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_workflow.contracts.common.types import JsonValue


class DefaultBindingMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ports: list[str]
    source_paths: list[str]


class DefaultBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: str
    match: DefaultBindingMatch


class InputPortDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    direction: Literal["input"] = "input"
    required: bool
    cardinality: Literal["single", "optional", "multiple"]
    schema_: dict[str, Any] = Field(alias="schema")
    description: str | None = None
    default_bindings: list[DefaultBinding] = Field(default_factory=list)


class OutputPortDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    direction: Literal["output"] = "output"
    required: bool
    cardinality: Literal["single", "optional", "multiple"]
    schema_: dict[str, Any] = Field(alias="schema")
    description: str | None = None


class CredentialSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credential_type: str
    required: bool
    description: str | None = None


class ResourceSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    resource_type: Literal["dataset", "watchlist", "artifact_collection", "other"]
    required: bool
    description: str | None = None


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retryable: bool
    cancellable: bool
    side_effecting: bool
    execution_mode: Literal["inline", "durable-task"]
    emits_progress: bool
    resumable: bool


class UiMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    icon: str
    color_token: str
    inspector: str | None = None


class NodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str
    display_name: str
    description: str
    category: Literal[
        "trigger", "data", "control", "ai", "rag", "human", "action", "market", "research"
    ]
    execution_owner: Literal["control-plane", "execution-engine"]
    inputs: list[InputPortDefinition]
    outputs: list[OutputPortDefinition]
    config_schema: dict[str, Any]
    credential_slots: list[CredentialSlot]
    resource_slots: list[ResourceSlot]
    capabilities: Capabilities
    ui: UiMetadata

    def default_bindings_by_port(self) -> dict[str, list[DefaultBinding]]:
        return {port.name: list(port.default_bindings) for port in self.inputs}

    def is_durable_task(self) -> bool:
        return self.capabilities.execution_mode == "durable-task"


class ManifestValidationError(Exception):
    """Raised when a manifest fails JSON Schema validation."""


def manifest_from_dict(data: dict[str, JsonValue]) -> NodeManifest:
    """Parse and validate a manifest dict into a ``NodeManifest`` model."""
    return NodeManifest.model_validate(data)
