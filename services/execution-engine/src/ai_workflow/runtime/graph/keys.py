from __future__ import annotations


class RuntimeKeys:
    """Well-known ``WorkflowState.runtime`` keys persisted in checkpoints."""

    SCHEDULER = "_scheduler"
    INTERRUPT = "_interrupt"
    DEFINITION = "_definition"
    DEFINITION_HASH = "_definition_hash"
    FOREACH_FRAMES = "_for_each_frames"
    COLLECT_INJECT = "_collect_inject"
    STATE_ROOT = "_state_root"
    LOOP_ITERATIONS = "_loop_iterations"
    WORKSPACE_ID = "_workspace_id"
    PROJECT_ID = "_project_id"
    DEADLINE = "_deadline"
    MAX_FAN_OUT_ITEMS = "_max_fan_out_items"
    FOREACH_ITEM = "_foreach_item"
