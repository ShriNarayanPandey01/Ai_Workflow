from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from ai_workflow.contracts.nodes.catalog_loader import load_catalog_manifests
from ai_workflow.contracts.nodes.manifest import NodeManifest
from ai_workflow.contracts.workflow.definition import (
    CONDITION_SCHEMA_ID,
    WORKFLOW_SCHEMA_ID,
    WorkflowDefinition,
    WorkflowNode,
)

from ai_workflow.runtime.semantics.bindings import (
    bindings_for_node,
    edge_connects,
    infer_pass_through_bindings,
    is_valid_json_pointer,
)
from ai_workflow.runtime.semantics.schema_paths import schema_at_pointer, schemas_compatible

LOOP_NODE_TYPE = "control.loop@1"
ITERATION_PORT = "iteration"


def _base_node_type(node_type: str) -> str:
    """Return the version-stripped base of a ``name@version`` node type."""
    return node_type.split("@", 1)[0]


@dataclass(frozen=True, slots=True)
class SemanticError:
    """A single semantic validation failure with a stable error code."""

    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class SemanticValidationError(ValueError):
    """Raised when a workflow fails semantic validation."""

    def __init__(self, errors: list[SemanticError]) -> None:
        """Aggregate semantic errors into one exception with a summary message."""
        self.errors = errors
        codes = ", ".join(sorted({error.code for error in errors}))
        super().__init__(f"Semantic validation failed: {codes}")


def validate_workflow_semantics(
    definition: WorkflowDefinition,
    *,
    contracts_root: Path,
    manifests: dict[str, NodeManifest] | None = None,
    max_loop_iterations: int = 100,
) -> None:
    """Validate a workflow beyond JSON Schema structural checks.

    Runs four passes and raises SemanticValidationError with all findings:
    1. Node configs — catalog type exists, config schema valid, loop bounds.
    2. Edge refs — edges reference real nodes and declared source ports.
    3. Cycles — only ``control.loop@1`` may own a strongly connected component.
    4. Bindings — pointer syntax, edge connectivity, and port schema compatibility.

    Args:
        definition: Parsed workflow to validate.
        contracts_root: Root of contract schemas and node catalog.
        manifests: Pre-loaded catalog; loaded from disk when omitted.
        max_loop_iterations: Platform-wide cap enforced on loop nodes.
    """
    CatalogSemanticValidator(
        contracts_root=contracts_root,
        max_loop_iterations=max_loop_iterations,
        manifests=manifests,
    ).validate(definition)


def _validate_node_configs(
    definition: WorkflowDefinition,
    catalog: dict[str, NodeManifest],
    contracts_root: Path,
    max_loop_iterations: int,
) -> list[SemanticError]:
    """Validate each node type, config schema, and loop iteration bounds."""
    errors: list[SemanticError] = []
    registry = _schema_registry(contracts_root)

    catalog_base_types = {_base_node_type(node_type) for node_type in catalog}

    for node in definition.nodes:
        manifest = catalog.get(node.type)
        if manifest is None:
            # Distinguish an unsupported *version* of a known base type
            # (e.g. data.input@99 when only data.input@1 is catalogued) from a
            # genuinely unknown base type — the contracts declare separate codes.
            if _base_node_type(node.type) in catalog_base_types:
                errors.append(
                    SemanticError(
                        code="NODE_VERSION_UNSUPPORTED",
                        message=f"Unsupported version for node type {node.type}",
                        node_id=str(node.id),
                    )
                )
            else:
                errors.append(
                    SemanticError(
                        code="NODE_TYPE_UNKNOWN",
                        message=f"Unknown node type {node.type}",
                        node_id=str(node.id),
                    )
                )
            continue

        validator = Draft202012Validator(manifest.config_schema, registry=registry)
        config_errors = sorted(
            validator.iter_errors(node.config),
            key=lambda error: list(error.path),
        )
        if config_errors:
            first = config_errors[0]
            codes = ["NODE_CONFIG_INVALID"]
            if node.type == LOOP_NODE_TYPE and "max_iterations" not in node.config:
                codes.append("LOOP_UNBOUNDED")
            for code in codes:
                errors.append(
                    SemanticError(
                        code=code,
                        message=first.message,
                        node_id=str(node.id),
                    )
                )
            continue

        if node.type == LOOP_NODE_TYPE:
            max_iters = node.config.get("max_iterations")
            if not isinstance(max_iters, int) or max_iters < 1:
                errors.append(
                    SemanticError(
                        code="LOOP_UNBOUNDED",
                        message="control.loop@1 requires max_iterations >= 1",
                        node_id=str(node.id),
                    )
                )
            elif max_iters > max_loop_iterations:
                errors.append(
                    SemanticError(
                        code="LOOP_UNBOUNDED",
                        message=(
                            f"max_iterations {max_iters} exceeds platform cap "
                            f"{max_loop_iterations}"
                        ),
                        node_id=str(node.id),
                    )
                )

    return errors


FOREACH_BODY_FORBIDDEN_TYPES = frozenset(
    {
        "human.approval@1",
        "human.review@1",
        "control.for-each@1",
        "control.loop@1",
        "research.deep-research@1",
        "action.cleanup-plan@1",
        "action.cleanup-execute@1",
    }
)


def _validate_foreach_bodies(definition: WorkflowDefinition) -> list[SemanticError]:
    """Reject interrupts, nested fan-out, loops, and durable tasks inside for-each bodies."""
    from collections import defaultdict, deque

    errors: list[SemanticError] = []
    nodes_by_id = definition.node_by_id()
    outgoing: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for edge in definition.edges:
        outgoing[str(edge.source_node_id)][edge.source_port].append(edge)

    collect_ids = {
        str(node.id) for node in definition.nodes if node.type == "control.collect@1"
    }

    for node in definition.nodes:
        if node.type != "control.for-each@1":
            continue
        for_each_id = str(node.id)
        item_edges = outgoing.get(for_each_id, {}).get("item", [])
        body: set[str] = set()
        queue = deque(str(edge.target_node_id) for edge in item_edges)
        while queue:
            current = queue.popleft()
            if current in body or current == for_each_id or current in collect_ids:
                continue
            body.add(current)
            for edge in definition.edges:
                if str(edge.source_node_id) != current:
                    continue
                target = str(edge.target_node_id)
                if target not in body and target not in collect_ids:
                    queue.append(target)
        for body_id in body:
            body_node = nodes_by_id.get(body_id)
            if body_node is None:
                continue
            if body_node.type in FOREACH_BODY_FORBIDDEN_TYPES:
                errors.append(
                    SemanticError(
                        code="FOREACH_BODY_FORBIDDEN",
                        message=(
                            f"Node type {body_node.type} is not allowed inside "
                            "control.for-each@1 bodies"
                        ),
                        node_id=body_id,
                    )
                )
    return errors


def _validate_durable_nodes(
    definition: WorkflowDefinition,
    catalog: dict[str, NodeManifest],
) -> list[SemanticError]:
    """Durable-task nodes are legal once F15 executors exist; no extra check here."""
    del definition, catalog
    return []


def _validate_edge_refs(
    definition: WorkflowDefinition,
    catalog: dict[str, NodeManifest],
) -> list[SemanticError]:
    """Validate that edges reference existing nodes and declared source ports.

    * ``NODE_REF_MISSING`` — an edge endpoint is absent from ``nodes[]``.
    * ``PORT_UNKNOWN`` — an edge's ``source_port`` is not an output port declared
      by the source node's catalog manifest. Target ports are intentionally not
      checked: some control nodes (e.g. ``control.merge@1``) accept config-driven
      dynamic input ports, so an undeclared target port is legal.
    """
    nodes_by_id = definition.node_by_id()
    errors: list[SemanticError] = []

    for edge in definition.edges:
        edge_id = str(edge.id)
        source_id = str(edge.source_node_id)
        target_id = str(edge.target_node_id)

        source_node = nodes_by_id.get(source_id)
        if source_node is None:
            errors.append(
                SemanticError(
                    code="NODE_REF_MISSING",
                    message=f"Edge source node {source_id} does not exist",
                    edge_id=edge_id,
                )
            )
        if target_id not in nodes_by_id:
            errors.append(
                SemanticError(
                    code="NODE_REF_MISSING",
                    message=f"Edge target node {target_id} does not exist",
                    edge_id=edge_id,
                )
            )

        if source_node is None:
            continue
        manifest = catalog.get(source_node.type)
        if manifest is None:
            # An unknown/unsupported source node type is already reported by
            # _validate_node_configs; skip the port check to avoid a duplicate.
            continue
        output_ports = {port.name for port in manifest.outputs}
        if edge.source_port not in output_ports:
            errors.append(
                SemanticError(
                    code="PORT_UNKNOWN",
                    message=(
                        f"Source port {edge.source_port!r} is not declared by "
                        f"node type {source_node.type}"
                    ),
                    edge_id=edge_id,
                )
            )

    return errors


def _foreach_collect_node_ids(definition: WorkflowDefinition) -> set[str]:
    """Collect nodes whose items input is injected at runtime by for-each frames."""
    has_foreach = any(node.type == "control.for-each@1" for node in definition.nodes)
    if not has_foreach:
        return set()
    return {str(node.id) for node in definition.nodes if node.type == "control.collect@1"}


def _validate_bindings(
    definition: WorkflowDefinition,
    catalog: dict[str, NodeManifest],
) -> list[SemanticError]:
    """Validate explicit and inferred input bindings for every workflow node."""
    nodes_by_id = definition.node_by_id()
    ancestors = _ancestor_map(definition)
    errors: list[SemanticError] = []
    runtime_collect_ids = _foreach_collect_node_ids(definition)

    for node in definition.nodes:
        manifest = catalog.get(node.type)
        if manifest is None:
            continue

        node_id = str(node.id)
        incoming = definition.incoming_edges(node.id)
        effective = bindings_for_node(node, incoming)

        if node.input_bindings is None:
            inferred = infer_pass_through_bindings(node, incoming)
            pass_through_targets: dict[str, int] = {}
            multiple_ports = {
                input_port.name
                for input_port in manifest.inputs
                if input_port.cardinality == "multiple"
            }
            for binding in inferred:
                if binding.target_path in {"", "/"}:
                    key = binding.target_port
                    pass_through_targets[key] = pass_through_targets.get(key, 0) + 1
            for port_name, count in pass_through_targets.items():
                if count > 1 and port_name not in multiple_ports:
                    errors.append(
                        SemanticError(
                            code="BINDING_AMBIGUOUS",
                            message=(
                                f"Multiple incoming edges pass-through to input port "
                                f"{port_name!r}; explicit input_bindings required"
                            ),
                            node_id=node_id,
                        )
                    )

        covered_ports = {binding.target_port for binding in effective}
        for input_port in manifest.inputs:
            if input_port.required and input_port.name not in covered_ports:
                if (
                    node.type == "control.collect@1"
                    and input_port.name == "items"
                    and node_id in runtime_collect_ids
                ):
                    continue
                errors.append(
                    SemanticError(
                        code="BINDING_MISSING",
                        message=(
                            f"Required input port {input_port.name!r} has no binding"
                        ),
                        node_id=node_id,
                    )
                )

        input_ports_by_name = {port.name: port for port in manifest.inputs}
        target_counts: dict[tuple[str, str], int] = {}
        for binding in effective:
            target_key = (binding.target_port, binding.target_path)
            target_counts[target_key] = target_counts.get(target_key, 0) + 1

        reported_duplicates: set[tuple[str, str]] = set()
        for binding in effective:
            target_key = (binding.target_port, binding.target_path)
            target_port = input_ports_by_name.get(binding.target_port)
            allow_duplicate = (
                target_port is not None and target_port.cardinality == "multiple"
            )
            if (
                target_counts[target_key] > 1
                and not allow_duplicate
                and target_key not in reported_duplicates
            ):
                reported_duplicates.add(target_key)
                errors.append(
                    SemanticError(
                        code="BINDING_INCOMPATIBLE",
                        message=(
                            f"Duplicate binding target {binding.target_port!r} "
                            f"at {binding.target_path!r}"
                        ),
                        node_id=node_id,
                    )
                )

            if not is_valid_json_pointer(binding.source_path):
                errors.append(
                    SemanticError(
                        code="BINDING_INCOMPATIBLE",
                        message=f"Invalid source_path JSON Pointer: {binding.source_path!r}",
                        node_id=node_id,
                    )
                )
            if not is_valid_json_pointer(binding.target_path):
                errors.append(
                    SemanticError(
                        code="BINDING_INCOMPATIBLE",
                        message=f"Invalid target_path JSON Pointer: {binding.target_path!r}",
                        node_id=node_id,
                    )
                )

            if binding.source_node_id not in nodes_by_id:
                errors.append(
                    SemanticError(
                        code="BINDING_UNREACHABLE",
                        message=f"Unknown source node {binding.source_node_id}",
                        node_id=node_id,
                    )
                )
                continue

            if binding.source_node_id not in ancestors.get(node_id, set()):
                errors.append(
                    SemanticError(
                        code="BINDING_UNREACHABLE",
                        message=(
                            f"Source node {binding.source_node_id} is not upstream "
                            f"of {node_id}"
                        ),
                        node_id=node_id,
                    )
                )

            if binding.origin == "user" and not edge_connects(
                binding,
                target_node_id=node_id,
                edges=definition.edges,
            ):
                errors.append(
                    SemanticError(
                        code="BINDING_INCOMPATIBLE",
                        message=(
                            f"User binding requires edge from {binding.source_node_id}."
                            f"{binding.source_port} to {node_id}.{binding.target_port}"
                        ),
                        node_id=node_id,
                    )
                )

            source_node = nodes_by_id[binding.source_node_id]
            source_manifest = catalog.get(source_node.type)
            if source_manifest is None:
                continue

            source_schema = _output_port_schema(
                definition,
                source_node,
                source_manifest,
                binding.source_port,
            )
            target_schema = _input_port_schema(
                definition,
                node,
                manifest,
                binding.target_port,
            )

            source_subschema = schema_at_pointer(source_schema, binding.source_path)
            target_subschema = schema_at_pointer(target_schema, binding.target_path)

            if source_subschema is None and binding.source_path not in {"", "/"}:
                errors.append(
                    SemanticError(
                        code="BINDING_INCOMPATIBLE",
                        message=(
                            f"source_path {binding.source_path!r} does not resolve in "
                            f"output port {binding.source_port!r} schema"
                        ),
                        node_id=node_id,
                    )
                )
                continue

            if target_subschema is None and binding.target_path not in {"", "/"}:
                errors.append(
                    SemanticError(
                        code="BINDING_INCOMPATIBLE",
                        message=(
                            f"target_path {binding.target_path!r} does not resolve in "
                            f"input port {binding.target_port!r} schema"
                        ),
                        node_id=node_id,
                    )
                )
                continue

            if source_subschema is not None and target_subschema is not None:
                if not schemas_compatible(source_subschema, target_subschema):
                    errors.append(
                        SemanticError(
                            code="BINDING_INCOMPATIBLE",
                            message=(
                                f"source {binding.source_path!r} is not compatible with "
                                f"target {binding.target_path!r}"
                            ),
                            node_id=node_id,
                        )
                    )

    return errors


def _ancestor_map(definition: WorkflowDefinition) -> dict[str, set[str]]:
    """Map each node id to the set of structural ancestor node ids."""
    reverse: dict[str, list[str]] = {str(node.id): [] for node in definition.nodes}
    for edge in definition.edges:
        target = str(edge.target_node_id)
        if target not in reverse:
            # Dangling edge target — reported as NODE_REF_MISSING by
            # _validate_edge_refs; skip here so this map does not KeyError.
            continue
        reverse[target].append(str(edge.source_node_id))

    ancestors: dict[str, set[str]] = {}
    for node in definition.nodes:
        node_id = str(node.id)
        found: set[str] = set()
        stack = list(reverse[node_id])
        while stack:
            current = stack.pop()
            if current in found:
                continue
            found.add(current)
            stack.extend(reverse.get(current, []))
        ancestors[node_id] = found
    return ancestors


def _output_port_schema(
    definition: WorkflowDefinition,
    node: WorkflowNode,
    manifest: NodeManifest,
    port_name: str,
) -> dict[str, Any]:
    """Return the JSON Schema for an output port, with data-node fallbacks."""
    for port in manifest.outputs:
        if port.name == port_name:
            if node.type == "data.input@1" and port_name == "value":
                return definition.input_schema
            return port.schema_
    return {}


def _input_port_schema(
    definition: WorkflowDefinition,
    node: WorkflowNode,
    manifest: NodeManifest,
    port_name: str,
) -> dict[str, Any]:
    """Return the JSON Schema for an input port, with data-node fallbacks."""
    for port in manifest.inputs:
        if port.name == port_name:
            if node.type == "data.output@1" and port_name == "value":
                return definition.output_schema
            return port.schema_
    return {}


def _schema_registry(contracts_root: Path) -> Registry:
    """Build the JSON Schema registry used to validate node config schemas."""
    workflow_dir = contracts_root / "workflow"
    definition = json.loads(
        (workflow_dir / "definition.schema.json").read_text(encoding="utf-8")
    )
    condition = json.loads(
        (workflow_dir / "condition.schema.json").read_text(encoding="utf-8")
    )
    # Catalog manifests use relative refs like ../../workflow/condition.schema.json
    relative_condition_uri = "../../workflow/condition.schema.json"
    return Registry().with_resources(
        [
            (WORKFLOW_SCHEMA_ID, DRAFT202012.create_resource(definition)),
            (CONDITION_SCHEMA_ID, DRAFT202012.create_resource(condition)),
            (relative_condition_uri, DRAFT202012.create_resource(condition)),
        ]
    )


def _validate_cycles(definition: WorkflowDefinition) -> list[SemanticError]:
    """Reject arbitrary cycles; allow only SCCs owned by a single control.loop@1."""
    nodes_by_id = definition.node_by_id()
    adjacency: dict[str, list[tuple[str, str, str]]] = {node_id: [] for node_id in nodes_by_id}
    # adjacency[source] = list of (target, source_port, edge_id)

    for edge in definition.edges:
        source = str(edge.source_node_id)
        target = str(edge.target_node_id)
        if source not in nodes_by_id or target not in nodes_by_id:
            continue
        adjacency[source].append((target, edge.source_port, str(edge.id)))

    sccs = _tarjan_sccs(adjacency)
    errors: list[SemanticError] = []

    for scc in sccs:
        if len(scc) == 1:
            node_id = next(iter(scc))
            self_edges = [e for e in adjacency[node_id] if e[0] == node_id]
            if not self_edges:
                continue

        loop_owners = [
            node_id
            for node_id in scc
            if nodes_by_id[node_id].type == LOOP_NODE_TYPE
        ]
        if len(loop_owners) != 1:
            errors.append(
                SemanticError(
                    code="ARBITRARY_CYCLE",
                    message=(
                        "Cycle between nodes without exactly one owning "
                        f"control.loop@1: {sorted(scc)}"
                    ),
                )
            )
            continue

        owner_id = loop_owners[0]
        # Every edge from an SCC node to the loop owner must target iteration,
        # OR be an internal forward edge. Back-edges into the loop must hit iteration.
        for source_id in scc:
            for target_id, _source_port, edge_id in adjacency[source_id]:
                if target_id != owner_id:
                    continue
                # Find the edge's target_port from definition
                edge = next(e for e in definition.edges if str(e.id) == edge_id)
                if str(edge.target_node_id) == owner_id and edge.target_port != ITERATION_PORT:
                    # Edges from outside entering loop initially also target iteration;
                    # inside the SCC, body→done would be wrong. Only flag back-edges
                    # that re-enter the loop on a non-iteration port.
                    if source_id in scc and source_id != owner_id:
                        errors.append(
                            SemanticError(
                                code="ARBITRARY_CYCLE",
                                message=(
                                    "Loop back-edge must target the loop iteration port"
                                ),
                                node_id=owner_id,
                                edge_id=edge_id,
                            )
                        )

        # After removing edges into owner.iteration from within SCC, remaining
        # graph among SCC should not have other cycles bypassing the loop.
        # LLD step 6: remove permitted loop-back edges and verify acyclic.
        permitted_back: set[str] = set()
        for source_id in scc:
            for target_id, _source_port, edge_id in adjacency[source_id]:
                if target_id != owner_id:
                    continue
                edge = next(e for e in definition.edges if str(e.id) == edge_id)
                if edge.target_port == ITERATION_PORT and source_id != owner_id:
                    permitted_back.add(edge_id)

        reduced_adj: dict[str, list[str]] = {node_id: [] for node_id in scc}
        for source_id in scc:
            for target_id, _source_port, edge_id in adjacency[source_id]:
                if target_id not in scc:
                    continue
                if edge_id in permitted_back:
                    continue
                reduced_adj[source_id].append(target_id)

        if _has_cycle(reduced_adj):
            errors.append(
                SemanticError(
                    code="ARBITRARY_CYCLE",
                    message=f"Cycle remains after removing loop-back edges in {sorted(scc)}",
                )
            )

    return errors


def _tarjan_sccs(
    adjacency: dict[str, list[tuple[str, str, str]]],
) -> list[set[str]]:
    """Find strongly connected components in the workflow adjacency graph."""
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    result: list[set[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target, _port, _edge_id in adjacency.get(node, []):
            if target not in indices:
                strongconnect(target)
                lowlink[node] = min(lowlink[node], lowlink[target])
            elif target in on_stack:
                lowlink[node] = min(lowlink[node], indices[target])

        if lowlink[node] == indices[node]:
            component: set[str] = set()
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.add(member)
                if member == node:
                    break
            result.append(component)

    for node_id in adjacency:
        if node_id not in indices:
            strongconnect(node_id)

    return result


def _has_cycle(adjacency: dict[str, list[str]]) -> bool:
    """Return whether a directed graph contains a cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adjacency[node]:
            if color[neighbor] == GRAY:
                return True
            if color[neighbor] == WHITE and dfs(neighbor):
                return True
        color[node] = BLACK
        return False

    return any(dfs(node) for node in adjacency if color[node] == WHITE)


def build_state_root(
    *,
    node_outputs: dict[str, dict[str, Any]],
    loop_iterations: dict[str, int],
    runtime: dict[str, Any],
    loop: Any | None = None,
) -> dict[str, Any]:
    """Build the state root object exposed to condition expressions and nodes."""
    root: dict[str, Any] = {
        "node_outputs": node_outputs,
        "loop_iterations": loop_iterations,
        "runtime": {k: v for k, v in runtime.items() if not str(k).startswith("_")},
    }
    if loop is not None:
        root["loop"] = loop
    return root


class SemanticValidator(ABC):
    """Replaceable workflow semantic checks and state-root construction."""

    @abstractmethod
    def validate(self, definition: WorkflowDefinition) -> None: ...

    @abstractmethod
    def build_state_root(
        self,
        *,
        node_outputs: dict[str, dict[str, Any]],
        loop_iterations: dict[str, int],
        runtime: dict[str, Any],
        loop: Any | None = None,
    ) -> dict[str, Any]: ...


class CatalogSemanticValidator(SemanticValidator):
    """Catalog-backed semantic validation (EnvelopeValidator-style)."""

    def __init__(
        self,
        *,
        contracts_root: Path,
        max_loop_iterations: int = 100,
        manifests: dict[str, NodeManifest] | None = None,
    ) -> None:
        self._contracts_root = contracts_root
        self._max_loop_iterations = max_loop_iterations
        self._manifests = manifests

    def validate(self, definition: WorkflowDefinition) -> None:
        catalog = self._manifests or load_catalog_manifests(self._contracts_root)
        errors: list[SemanticError] = []
        errors.extend(
            _validate_node_configs(
                definition, catalog, self._contracts_root, self._max_loop_iterations
            )
        )
        errors.extend(_validate_edge_refs(definition, catalog))
        errors.extend(_validate_cycles(definition))
        errors.extend(_validate_bindings(definition, catalog))
        errors.extend(_validate_foreach_bodies(definition))
        errors.extend(_validate_durable_nodes(definition, catalog))
        if errors:
            raise SemanticValidationError(errors)

    def build_state_root(
        self,
        *,
        node_outputs: dict[str, dict[str, Any]],
        loop_iterations: dict[str, int],
        runtime: dict[str, Any],
        loop: Any | None = None,
    ) -> dict[str, Any]:
        return build_state_root(
            node_outputs=node_outputs,
            loop_iterations=loop_iterations,
            runtime=runtime,
            loop=loop,
        )
