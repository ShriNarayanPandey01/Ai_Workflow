from __future__ import annotations

from ai_workflow.contracts.workflow.definition import InputBinding, WorkflowEdge, WorkflowNode
from ai_workflow.runtime.bindings import (
    bindings_for_node,
    infer_pass_through_bindings,
    is_valid_json_pointer,
    resolve_inputs,
)


def _edge() -> WorkflowEdge:
    return WorkflowEdge.model_validate(
        {
            "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
            "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            "source_port": "value",
            "target_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            "target_port": "value",
            "label": None,
            "condition": None,
        }
    )


def test_infer_pass_through_binding_from_edge() -> None:
    target = WorkflowNode.model_validate(
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            "type": "data.output@1",
            "position": {"x": 1, "y": 2},
            "config": {},
            "credential_refs": {},
            "resource_refs": {},
        }
    )
    bindings = infer_pass_through_bindings(target, [_edge()])

    assert len(bindings) == 1
    assert bindings[0].target_port == "value"
    assert bindings[0].source_port == "value"
    assert bindings[0].origin == "pass_through"


def test_resolve_inputs_passes_whole_port_value() -> None:
    bindings = infer_pass_through_bindings(
        WorkflowNode.model_validate(
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
                "type": "data.output@1",
                "position": {"x": 1, "y": 2},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            }
        ),
        [_edge()],
    )
    node_outputs = {
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1": {
            "value": {"order_id": "ord-1"},
        }
    }

    inputs = resolve_inputs(bindings, node_outputs)

    assert inputs == {"value": {"order_id": "ord-1"}}


def test_bindings_for_node_uses_explicit_bindings() -> None:
    target = WorkflowNode.model_validate(
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            "type": "data.output@1",
            "position": {"x": 1, "y": 2},
            "config": {},
            "credential_refs": {},
            "resource_refs": {},
            "input_bindings": [
                {
                    "target_port": "value",
                    "target_path": "/order_id",
                    "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                    "source_port": "value",
                    "source_path": "/order_id",
                    "origin": "user",
                }
            ],
        }
    )

    bindings = bindings_for_node(target, [_edge()])

    assert len(bindings) == 1
    assert bindings[0].target_path == "/order_id"
    assert bindings[0].origin == "user"


def test_bindings_for_node_empty_explicit_list_skips_inference() -> None:
    target = WorkflowNode.model_validate(
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            "type": "data.output@1",
            "position": {"x": 1, "y": 2},
            "config": {},
            "credential_refs": {},
            "resource_refs": {},
            "input_bindings": [],
        }
    )

    bindings = bindings_for_node(target, [_edge()])

    assert bindings == []


def test_resolve_inputs_maps_field_level_paths() -> None:
    binding = InputBinding.model_validate(
        {
            "target_port": "value",
            "target_path": "/order_id",
            "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            "source_port": "value",
            "source_path": "/order_id",
            "origin": "user",
        }
    )
    target = WorkflowNode.model_validate(
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            "type": "data.output@1",
            "position": {"x": 1, "y": 2},
            "config": {},
            "credential_refs": {},
            "resource_refs": {},
            "input_bindings": [binding.model_dump(mode="json")],
        }
    )
    bindings = bindings_for_node(target, [_edge()])
    node_outputs = {
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1": {
            "value": {"order_id": "ord-1", "priority": "high"},
        }
    }

    inputs = resolve_inputs(bindings, node_outputs)

    assert inputs == {"value": {"order_id": "ord-1"}}


def test_is_valid_json_pointer() -> None:
    assert is_valid_json_pointer("/")
    assert is_valid_json_pointer("")
    assert is_valid_json_pointer("/order_id")
    assert is_valid_json_pointer("/a~1b")
    assert not is_valid_json_pointer("order_id")
    assert not is_valid_json_pointer("/foo~")
