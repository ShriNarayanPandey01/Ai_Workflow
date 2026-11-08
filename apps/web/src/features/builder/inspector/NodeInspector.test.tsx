import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { InputBinding, NodeManifest, WorkflowDefinition, WorkflowNode } from "@/api/types"
import { BindingsTable } from "./NodeInspector"

const targetNode: WorkflowNode = {
  id: "target-node",
  type: "test.target@1",
  position: { x: 0, y: 0 },
  config: {},
}

const targetManifest: NodeManifest = {
  type: "test.target@1",
  display_name: "Target",
  description: "",
  category: "data",
  execution_owner: "execution-engine",
  inputs: [
    {
      name: "variables",
      direction: "input",
      required: true,
      cardinality: "single",
      schema: { type: "object", properties: { known: { type: "string" } } },
    },
  ],
  outputs: [],
  config_schema: { type: "object" },
  credential_slots: [],
  resource_slots: [],
  ui: { icon: "box", color_token: "data" },
}

const workflow: WorkflowDefinition = {
  schema_version: "1.0",
  workflow_id: "11111111-1111-4111-8111-111111111100",
  name: "Legacy binding",
  input_schema: { type: "object" },
  output_schema: { type: "object" },
  nodes: [targetNode],
  edges: [],
  execution_policy: {
    timeout_seconds: 300,
    max_node_executions: 50,
    max_parallel_nodes: 4,
    max_fan_out_items: 100,
    max_task_seconds: 600,
    max_provider_calls: 100,
    max_artifact_bytes: 10485760,
    default_retry: {
      max_attempts: 3,
      initial_backoff_ms: 500,
      max_backoff_ms: 10000,
      multiplier: 2,
      jitter: true,
    },
  },
}

describe("BindingsTable", () => {
  it("preserves an unresolved legacy mapping until it is explicitly removed", () => {
    const binding: InputBinding = {
      target_port: "variables",
      target_path: "/legacy",
      source_node_id: "deleted-source",
      source_port: "value",
      source_path: "/legacy",
      origin: "user",
    }
    const onChange = vi.fn()

    render(
      <BindingsTable
        definition={workflow}
        catalog={[targetManifest]}
        node={targetNode}
        bindings={[binding]}
        onChange={onChange}
      />,
    )

    expect(screen.getByText("Unresolved")).toBeInTheDocument()
    expect(screen.getByText("input.variables/legacy")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Remove mapping 1" }))
    expect(onChange).toHaveBeenCalledWith([])
  })
})