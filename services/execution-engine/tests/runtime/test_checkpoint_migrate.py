from __future__ import annotations

from ai_workflow.runtime.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    migrate_checkpoint,
    state_from_dict,
    state_to_dict,
)
from ai_workflow.runtime.scheduler_state import DEFINITION_KEY, INTERRUPT_KEY, SCHEDULER_KEY
from ai_workflow.runtime.state import WorkflowState


def test_migrate_v0_lifts_runtime_keys() -> None:
    v0 = {
        "node_outputs": {"n1": {"value": 1}},
        "loop_iterations": {},
        "task_refs": {},
        "runtime": {
            SCHEDULER_KEY: {"pending": ["n1"], "produced": []},
            INTERRUPT_KEY: {"waiting_reason": "HUMAN"},
            DEFINITION_KEY: {"id": "wf"},
            "_definition_hash": "abc",
            "run_input": {"x": 1},
        },
    }
    migrated = migrate_checkpoint(v0)
    assert migrated["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert migrated["definition_hash"] == "abc"
    assert migrated["scheduler"]["pending"] == ["n1"]
    assert migrated["interrupt"]["waiting_reason"] == "HUMAN"
    assert migrated["definition"] == {"id": "wf"}
    assert migrated["runtime"] == {"run_input": {"x": 1}}
    assert SCHEDULER_KEY not in migrated["runtime"]


def test_round_trip_restores_runtime_helpers() -> None:
    state = WorkflowState(
        node_outputs={"node-1": {"value": {"order_id": "ord-1"}}},
        runtime={
            "run_input": {"order_id": "ord-1"},
            SCHEDULER_KEY: {"pending": []},
            DEFINITION_KEY: {"nodes": []},
            "_definition_hash": "deadbeef",
        },
    )
    restored = state_from_dict(state_to_dict(state))
    assert restored.node_outputs == state.node_outputs
    assert restored.runtime["run_input"] == {"order_id": "ord-1"}
    assert restored.runtime[SCHEDULER_KEY] == {"pending": []}
    assert restored.runtime[DEFINITION_KEY] == {"nodes": []}
    assert restored.runtime["_definition_hash"] == "deadbeef"
    envelope = state_to_dict(state)
    assert envelope["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert envelope["definition_hash"] == "deadbeef"
    assert "run_input" in envelope["runtime"]
    assert SCHEDULER_KEY not in envelope["runtime"]
