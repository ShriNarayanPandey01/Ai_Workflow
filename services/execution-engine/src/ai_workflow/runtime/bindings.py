from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.workflow.definition import WorkflowEdge, WorkflowNode


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    """A resolved edge mapping from a source port to a target input port."""

    target_port: str
    target_path: str
    source_node_id: str
    source_port: str
    source_path: str
    origin: Literal["pass_through", "user", "default"] = "pass_through"


def json_pointer_get(value: JsonValue, path: str) -> JsonValue:
    """Read a value from a JSON document using an RFC 6901 JSON Pointer."""
    if path in {"", "/"}:
        return value
    if not path.startswith("/"):
        msg = f"Invalid JSON Pointer: {path}"
        raise ValueError(msg)

    current: JsonValue = value
    for token in path.lstrip("/").split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict):
            msg = f"Cannot traverse token {token!r} in non-object value"
            raise ValueError(msg)
        current = current[key]
    return current


def json_pointer_set(target: JsonValue, path: str, value: JsonValue) -> JsonValue:
    """Write a value into a JSON document at the given JSON Pointer path."""
    if path in {"", "/"}:
        return value
    if not path.startswith("/"):
        msg = f"Invalid JSON Pointer: {path}"
        raise ValueError(msg)

    if not isinstance(target, dict):
        target = {}

    tokens = path.lstrip("/").split("/")
    current: dict[str, JsonValue] = target
    for token in tokens[:-1]:
        key = token.replace("~1", "/").replace("~0", "~")
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value

    leaf = tokens[-1].replace("~1", "/").replace("~0", "~")
    current[leaf] = value
    return target


def infer_pass_through_bindings(
    node: WorkflowNode,
    incoming_edges: list[WorkflowEdge],
) -> list[ResolvedBinding]:
    """Create one-to-one pass-through bindings from incoming workflow edges."""
    bindings: list[ResolvedBinding] = []
    for edge in incoming_edges:
        if str(edge.target_node_id) != str(node.id):
            continue
        bindings.append(
            ResolvedBinding(
                target_port=edge.target_port,
                target_path="/",
                source_node_id=str(edge.source_node_id),
                source_port=edge.source_port,
                source_path="/",
                origin="pass_through",
            )
        )
    return bindings


def is_valid_json_pointer(path: str) -> bool:
    """Return whether a string is a syntactically valid RFC 6901 JSON Pointer."""
    if path in {"", "/"}:
        return True
    if not path.startswith("/"):
        return False
    for token in path.lstrip("/").split("/"):
        if token == "":
            return False
        if "~" in token:
            idx = 0
            while idx < len(token):
                tilde = token.find("~", idx)
                if tilde == -1:
                    break
                if tilde == len(token) - 1 or token[tilde + 1] not in {"0", "1"}:
                    return False
                idx = tilde + 2
    return True


def edge_connects(
    binding: ResolvedBinding,
    *,
    target_node_id: str,
    edges: list[WorkflowEdge],
) -> bool:
    """Return whether a structural edge matches the binding's source and target ports."""
    for edge in edges:
        if (
            str(edge.source_node_id) == binding.source_node_id
            and str(edge.target_node_id) == target_node_id
            and edge.source_port == binding.source_port
            and edge.target_port == binding.target_port
        ):
            return True
    return False


def bindings_for_node(
    node: WorkflowNode,
    incoming_edges: list[WorkflowEdge],
) -> list[ResolvedBinding]:
    """Resolve input bindings for a node before execution.

    Returns explicit ``node.input_bindings`` when present; otherwise infers
    one-to-one pass-through bindings from incoming edges (source port maps to
    target port at JSON Pointer ``/``).
    """
    if node.input_bindings is not None:
        return [
            ResolvedBinding(
                target_port=binding.target_port,
                target_path=binding.target_path,
                source_node_id=str(binding.source_node_id),
                source_port=binding.source_port,
                source_path=binding.source_path,
                origin=binding.origin,
            )
            for binding in node.input_bindings
        ]
    return infer_pass_through_bindings(node, incoming_edges)


def resolve_inputs(
    bindings: list[ResolvedBinding],
    node_outputs: dict[str, dict[str, JsonValue]],
) -> dict[str, JsonValue]:
    """Resolve node inputs from bindings, requiring every source port to exist."""
    return _resolve_bindings(bindings, node_outputs, skip_missing=False)


def resolve_available_inputs(
    bindings: list[ResolvedBinding],
    node_outputs: dict[str, dict[str, JsonValue]],
    *,
    production_order: dict[tuple[str, str], int] | None = None,
    multiple_ports: set[str] | None = None,
) -> dict[str, JsonValue]:
    """Resolve node inputs from bindings that have produced source values.

    Skips bindings whose source port has not been produced yet, which allows
    partially-ready nodes to run when only some inputs are available.

    When multiple bindings target the same port and ``production_order`` is
    provided, selects the binding whose ``(source_node_id, source_port)``
    has the highest sequence number. This disambiguates loop back-edges where
    both the initial and iterated values are reachable.
    """
    if production_order is None:
        return _resolve_bindings(
            bindings,
            node_outputs,
            skip_missing=True,
            multiple_ports=multiple_ports,
        )

    by_port: dict[str, list[ResolvedBinding]] = {}
    for binding in bindings:
        by_port.setdefault(binding.target_port, []).append(binding)

    selected: list[ResolvedBinding] = []
    accumulate_ports = multiple_ports or set()
    for port_name, port_bindings in by_port.items():
        if port_name in accumulate_ports:
            selected.extend(port_bindings)
            continue
        available = [
            binding
            for binding in port_bindings
            if binding.source_port
            in node_outputs.get(binding.source_node_id, {})
        ]
        if not available:
            continue
        available.sort(
            key=lambda binding: production_order.get(
                (binding.source_node_id, binding.source_port),
                -1,
            )
        )
        selected.append(available[-1])

    return _resolve_bindings(
        selected,
        node_outputs,
        skip_missing=False,
        multiple_ports=multiple_ports,
    )


def _resolve_bindings(
    bindings: list[ResolvedBinding],
    node_outputs: dict[str, dict[str, JsonValue]],
    *,
    skip_missing: bool,
    multiple_ports: set[str] | None = None,
) -> dict[str, JsonValue]:
    """Materialize target input ports from binding definitions and node outputs."""
    inputs: dict[str, JsonValue] = {}
    accumulate_ports = multiple_ports or set()

    for binding in bindings:
        source_ports = node_outputs.get(binding.source_node_id, {})
        if binding.source_port not in source_ports:
            if skip_missing:
                continue
            msg = (
                f"Missing source port {binding.source_port!r} "
                f"on node {binding.source_node_id}"
            )
            raise KeyError(msg)

        source_value = source_ports[binding.source_port]
        extracted = json_pointer_get(source_value, binding.source_path)

        if binding.target_port in accumulate_ports and binding.target_path in {"", "/"}:
            existing_list = inputs.get(binding.target_port)
            if not isinstance(existing_list, list):
                existing_list = []
            existing_list.append(extracted)
            inputs[binding.target_port] = existing_list
            continue

        existing = inputs.get(binding.target_port)
        if existing is None:
            port_value: JsonValue = {} if binding.target_path not in {"", "/"} else extracted
            if binding.target_path not in {"", "/"}:
                port_value = json_pointer_set(port_value, binding.target_path, extracted)
            inputs[binding.target_port] = port_value
        else:
            if binding.target_path in {"", "/"}:
                inputs[binding.target_port] = extracted
            else:
                if not isinstance(existing, dict):
                    existing = {}
                inputs[binding.target_port] = json_pointer_set(
                    existing,
                    binding.target_path,
                    extracted,
                )

    return inputs
