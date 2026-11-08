import { describe, expect, it } from "vitest"
import { useWorkflowEditorStore } from "./workflowEditorStore"
import type { WorkflowDefinition } from "@/api/types"

const definition = (): WorkflowDefinition => ({
  schema_version: "1.0",
  workflow_id: "11111111-1111-4111-8111-111111111101",
  name: "t",
  input_schema: { type: "object" },
  output_schema: { type: "object" },
  nodes: [],
  edges: [],
  execution_policy: {
    timeout_seconds: 1,
    max_node_executions: 1,
    max_parallel_nodes: 1,
    max_fan_out_items: 1,
    max_task_seconds: 1,
    max_provider_calls: 1,
    max_artifact_bytes: 1,
    default_retry: { max_attempts: 1, initial_backoff_ms: 1, max_backoff_ms: 1, multiplier: 1, jitter: false },
  },
})

describe("workflowEditorStore", () => {
  it("tracks dirty and undo", () => {
    const def = definition()
    useWorkflowEditorStore.getState().load(1, def)
    useWorkflowEditorStore.getState().mutate((current) => ({ ...current, name: "changed" }))
    expect(useWorkflowEditorStore.getState().dirty).toBe(true)
    expect(useWorkflowEditorStore.getState().definition?.name).toBe("changed")
    useWorkflowEditorStore.getState().undo()
    expect(useWorkflowEditorStore.getState().definition?.name).toBe("t")
    useWorkflowEditorStore.getState().redo()
    expect(useWorkflowEditorStore.getState().definition?.name).toBe("changed")
  })
})
