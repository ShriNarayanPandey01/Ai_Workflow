import { describe, expect, it } from "vitest"
import { localValidate } from "./localValidate"
import type { WorkflowDefinition } from "@/api/types"

const base = (): WorkflowDefinition => ({
  schema_version: "1.0",
  workflow_id: "11111111-1111-4111-8111-111111111101",
  name: "t",
  input_schema: { type: "object" },
  output_schema: { type: "object" },
  nodes: [
    { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", type: "data.input@1", position: { x: 0, y: 0 }, config: {} },
  ],
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

describe("localValidate", () => {
  it("flags missing node refs", () => {
    const def = base()
    def.edges.push({
      id: "e",
      source_node_id: "missing",
      source_port: "value",
      target_node_id: def.nodes[0].id,
      target_port: "value",
    })
    expect(localValidate(def).some((e) => e.code === "MISSING_NODE_REF")).toBe(true)
  })

  it("requires loop maxIterations", () => {
    const def = base()
    def.nodes.push({
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
      type: "control.loop@1",
      position: { x: 1, y: 1 },
      config: {},
    })
    expect(localValidate(def).some((e) => e.code === "UNBOUNDED_LOOP")).toBe(true)
  })
})
